from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from branches.models import Branch
from dailyreports.models import DailyReport
from purchasing.models import PurchaseRecord

from .analysis import build_monthly_analysis


def _pct_delta(curr, prev):
    if not prev:
        return 0.0
    return round((curr - prev) / prev * 100, 1)


class DashboardSummaryView(APIView):
    """Real aggregation over DailyReport/PurchaseRecord — admins see every
    branch combined, branch accounts see only their own. Numbers will look
    sparse until branches have actually logged daily reports for recent
    dates; that's an honest reflection of the data, not a bug."""

    def get(self, request):
        user = request.user
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)

        reports = DailyReport.objects.all()
        purchases = PurchaseRecord.objects.all()
        if user.role == user.Role.ADMIN:
            reports = reports.filter(branch__organization_id=user.organization_id)
            purchases = purchases.filter(branch__organization_id=user.organization_id)
        else:
            reports = reports.filter(branch_id=user.branch_id)
            purchases = purchases.filter(branch_id=user.branch_id)

        def day_totals(d):
            rows = reports.filter(date=d)
            revenue = rows.aggregate(s=Sum('total_revenue'))['s'] or 0
            customers = rows.aggregate(s=Sum('total_customers'))['s'] or 0
            return revenue, customers

        today_revenue, today_customers = day_totals(today)
        yesterday_revenue, yesterday_customers = day_totals(yesterday)

        today_avg_spend = round(today_revenue / today_customers) if today_customers else 0
        yesterday_avg_spend = round(yesterday_revenue / yesterday_customers) if yesterday_customers else 0

        this_month_start = today.replace(day=1)
        last_month_end = this_month_start - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)

        monthly_purchasing = purchases.filter(
            date__gte=this_month_start, date__lte=today,
        ).aggregate(s=Sum('amount'))['s'] or 0
        last_month_purchasing = purchases.filter(
            date__gte=last_month_start, date__lte=last_month_end,
        ).aggregate(s=Sum('amount'))['s'] or 0

        revenue_trend = []
        for i in range(13, -1, -1):
            d = today - timedelta(days=i)
            rev, _ = day_totals(d)
            revenue_trend.append({'date': d.isoformat(), 'revenue': rev})

        branch_revenue_today = [
            {'branchId': row['branch_id'], 'revenue': row['revenue']}
            for row in reports.filter(date=today).values('branch_id').annotate(revenue=Sum('total_revenue'))
        ]

        return Response({
            'todayRevenue': today_revenue,
            'todayRevenueDeltaPct': _pct_delta(today_revenue, yesterday_revenue),
            'customerCount': today_customers,
            'customerCountDelta': today_customers - yesterday_customers,
            'avgSpend': today_avg_spend,
            'avgSpendDeltaPct': _pct_delta(today_avg_spend, yesterday_avg_spend),
            'monthlyPurchasing': monthly_purchasing,
            'monthlyPurchasingDeltaPct': _pct_delta(monthly_purchasing, last_month_purchasing),
            'revenueTrend': revenue_trend,
            'branchRevenueToday': branch_revenue_today,
        })


class MonthlyAnalysisView(APIView):
    """GET /api/dashboard/monthly-analysis/?month=YYYY-MM&branch=<id>

    admin with no branch param sees every branch combined; admin with a
    branch param sees just that one. branch accounts always see their own
    branch only — a mismatched or missing branch param from a branch
    account is corrected to their own, never honored as an escalation.
    staff gets 403 via the project-wide DenyStaffRole default (this view
    declares no permission_classes override, so it inherits that)."""

    def get(self, request):
        user = request.user
        month_param = request.query_params.get('month')
        if not month_param:
            raise ValidationError({'month': ['Required, format YYYY-MM.']})
        try:
            year_str, month_str = month_param.split('-')
            year, month = int(year_str), int(month_str)
            if not (1 <= month <= 12):
                raise ValueError
        except ValueError:
            raise ValidationError({'month': ['Must be in YYYY-MM format.']})

        branch_param = request.query_params.get('branch')
        if user.role == user.Role.ADMIN:
            org_branches = Branch.objects.filter(organization_id=user.organization_id)
            if branch_param:
                if not org_branches.filter(id=branch_param).exists():
                    raise ValidationError({'branch': ['Unknown branch.']})
                branch_ids = [branch_param]
                is_admin_all_branches = False
            else:
                branch_ids = list(org_branches.values_list('id', flat=True))
                is_admin_all_branches = True
        else:
            # A branch account can never see another branch's data, even by
            # explicitly requesting it — the param is silently corrected,
            # not honored or rejected as an error, since "just show me my
            # own data" is what the UI actually asked for either way.
            branch_ids = [user.branch_id]
            is_admin_all_branches = False

        result = build_monthly_analysis(
            branch_ids=branch_ids, year=year, month=month, is_admin_all_branches=is_admin_all_branches,
        )
        return Response(result)
