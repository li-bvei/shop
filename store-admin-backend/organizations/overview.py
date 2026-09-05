"""Platform-wide overview for the super admin — one row per tenant plus
totals. Deliberately high-level: counts and this-month money, no drill-down
into any single chain's operational data (that's what each chain's own
admin login is for)."""
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Sum

from accounts.models import User
from branches.models import Branch
from common.features import FEATURE_REGISTRY, enabled_features_for_org
from dailyreports.models import DailyReport
from purchasing.models import PurchaseRecord

from .models import Organization


def _month_range(today):
    start = today.replace(day=1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end.replace(day=1)
    return start, prev_start, prev_end


def _pct(curr, prev):
    if not prev:
        return None
    return round(float((curr - prev) / prev * 100), 1)


def build_platform_overview(today=None):
    today = today or date.today()
    m_start, pm_start, pm_end = _month_range(today)

    orgs = list(Organization.objects.all())
    branches = list(Branch.objects.all())
    branches_by_org = {}
    for b in branches:
        branches_by_org.setdefault(b.organization_id, []).append(b.id)

    # accounts per org, split by active / role
    acct_rows = (
        User.objects.values('organization_id', 'role', 'is_active')
        .annotate(n=Count('id'))
    )
    accounts_by_org = {}
    for r in acct_rows:
        d = accounts_by_org.setdefault(r['organization_id'], {'total': 0, 'active': 0, 'inactive': 0})
        d['total'] += r['n']
        d['active' if r['is_active'] else 'inactive'] += r['n']

    def money_for(branch_ids, start, end):
        if not branch_ids:
            return Decimal('0'), 0, Decimal('0')
        rep = DailyReport.objects.filter(branch_id__in=branch_ids, date__gte=start, date__lte=end).aggregate(
            rev=Sum('total_revenue'), cust=Sum('total_customers'),
        )
        pur = PurchaseRecord.objects.filter(branch_id__in=branch_ids, date__gte=start, date__lte=end).aggregate(
            amt=Sum('amount'),
        )
        return (rep['rev'] or Decimal('0'), rep['cust'] or 0, pur['amt'] or Decimal('0'))

    # loyalty (promotions) counts — imported lazily so a deploy without the
    # app still works
    customers_by_org = {}
    active_campaigns_by_org = {}
    try:
        from promotions.models import Campaign, Customer

        for r in Customer.objects.values('organization_id').annotate(n=Count('id')):
            customers_by_org[r['organization_id']] = r['n']
        for c in Campaign.objects.filter(status=Campaign.Status.ACTIVE).select_related('branch'):
            active_campaigns_by_org[c.branch.organization_id] = active_campaigns_by_org.get(
                c.branch.organization_id, 0,
            ) + 1
    except Exception:  # pragma: no cover - promotions optional
        pass

    org_rows = []
    tot_rev = tot_prev_rev = tot_pur = Decimal('0')
    tot_cust = tot_accounts = tot_active_accounts = 0
    for org in orgs:
        bids = branches_by_org.get(org.id, [])
        rev, cust, pur = money_for(bids, m_start, today)
        prev_rev, _, _ = money_for(bids, pm_start, pm_end)
        acc = accounts_by_org.get(org.id, {'total': 0, 'active': 0, 'inactive': 0})
        enabled = enabled_features_for_org(org.id)
        org_rows.append({
            'id': org.id,
            'code': org.code,
            'name_zh': org.name_zh,
            'name_ja': org.name_ja,
            'active': org.active,
            'branch_count': len(bids),
            'accounts': acc,
            'features_enabled': len(enabled),
            'features_total': len(FEATURE_REGISTRY),
            'disabled_features': [k for k in FEATURE_REGISTRY if k not in enabled],
            'month_revenue': str(rev),
            'month_revenue_delta_pct': _pct(rev, prev_rev),
            'month_customers': cust,
            'month_purchasing': str(pur),
            'loyalty_customers': customers_by_org.get(org.id, 0),
            'active_campaigns': active_campaigns_by_org.get(org.id, 0),
        })
        tot_rev += rev
        tot_prev_rev += prev_rev
        tot_pur += pur
        tot_cust += cust
        tot_accounts += acc['total']
        tot_active_accounts += acc['active']

    org_rows.sort(key=lambda r: Decimal(r['month_revenue']), reverse=True)

    return {
        'month': m_start.isoformat()[:7],
        'totals': {
            'organizations': len(orgs),
            'branches': len(branches),
            'accounts': tot_accounts,
            'active_accounts': tot_active_accounts,
            'month_revenue': str(tot_rev),
            'month_revenue_delta_pct': _pct(tot_rev, tot_prev_rev),
            'month_customers': tot_cust,
            'month_purchasing': str(tot_pur),
            'loyalty_customers': sum(customers_by_org.values()),
        },
        'organizations': org_rows,
    }
