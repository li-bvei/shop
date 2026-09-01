"""Monthly operational report for one campaign (打卡与抽奖实施方案.md §13
运营报表 / 开发任务书 §8 phase 3). Read-only aggregation — no LLM, every
number traces to a row.
"""

from datetime import datetime, time

from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from .models import LotteryDraw, PointsLedger, RiskEvent, SpendVerification, Voucher


def _month_range(year: int, month: int):
    """[start, end) as timezone-aware datetimes in the app timezone — used
    instead of `__date`/`__month` lookups, which need MySQL's timezone
    tables loaded to work on aware columns."""
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(datetime(year, month, 1), time.min), tz)
    if month == 12:
        end = timezone.make_aware(datetime.combine(datetime(year + 1, 1, 1), time.min), tz)
    else:
        end = timezone.make_aware(datetime.combine(datetime(year, month + 1, 1), time.min), tz)
    return start, end


def build_campaign_report(campaign, year: int, month: int) -> dict:
    start, end = _month_range(year, month)
    org_id = campaign.branch.organization_id

    svs = SpendVerification.objects.filter(campaign=campaign, verified_at__gte=start, verified_at__lt=end)
    accepted = svs.filter(status=SpendVerification.Status.ACCEPTED)
    voided = svs.filter(status=SpendVerification.Status.VOIDED)

    staff_rows = []
    for row in (
        svs.values('verified_by', 'verified_by__first_name', 'verified_by__username')
        .annotate(
            count=Count('id'),
            total_amount=Sum('amount_yen'),
            avg_amount=Avg('amount_yen'),
            voids=Count('id', filter=Q(status=SpendVerification.Status.VOIDED)),
        )
        .order_by('-count')
    ):
        staff_rows.append({
            'staff': row['verified_by__first_name'] or row['verified_by__username'] or '—',
            'count': row['count'],
            'total_amount': row['total_amount'] or 0,
            'avg_amount': round(row['avg_amount'] or 0),
            'voids': row['voids'],
        })

    ledger = PointsLedger.objects.filter(
        customer__isnull=False, created_at__gte=start, created_at__lt=end,
        customer__organization_id=org_id,
    )

    def _abs_sum(reason):
        return abs(ledger.filter(reason=reason).aggregate(s=Sum('delta'))['s'] or 0)

    points = {
        'earned': _abs_sum(PointsLedger.Reason.SPEND),
        'spent_on_draws': _abs_sum(PointsLedger.Reason.DRAW),
        'spent_on_vouchers': _abs_sum(PointsLedger.Reason.VOUCHER),
        'refunded': _abs_sum(PointsLedger.Reason.DRAW_REFUND),
        'expired': _abs_sum(PointsLedger.Reason.EXPIRE),
        'adjusted': ledger.filter(reason=PointsLedger.Reason.ADJUST).aggregate(s=Sum('delta'))['s'] or 0,
    }

    draws = LotteryDraw.objects.filter(campaign=campaign, drawn_at__gte=start, drawn_at__lt=end)
    by_prize = [
        {'prize': r['prize_name_snapshot'] or '—', 'count': r['c']}
        for r in draws.values('prize_name_snapshot').annotate(c=Count('id')).order_by('-c')
    ]

    vouchers = Voucher.objects.filter(campaign=campaign, issued_at__gte=start, issued_at__lt=end)
    redeemed = Voucher.objects.filter(
        campaign=campaign, redeemed_at__gte=start, redeemed_at__lt=end, status=Voucher.Status.REDEEMED,
    )
    cash_face_redeemed = sum(
        int(v.config_snapshot.get('face_yen', 0)) for v in redeemed if v.reward_type == 'cash_voucher'
    )

    risk = RiskEvent.objects.filter(organization_id=org_id, created_at__gte=start, created_at__lt=end)
    risk_by_type = [
        {'event_type': r['event_type'], 'count': r['c']}
        for r in risk.values('event_type').annotate(c=Count('id')).order_by('-c')
    ]

    return {
        'month': f'{year:04d}-{month:02d}',
        'spend': {
            'verifications': accepted.count(),
            'total_amount': accepted.aggregate(s=Sum('amount_yen'))['s'] or 0,
            'voided': voided.count(),
        },
        'staff_stats': staff_rows,
        'points': points,
        'draws': {
            'total': draws.count(),
            'won': draws.filter(status=LotteryDraw.Status.WON).count(),
            'refund': draws.filter(status=LotteryDraw.Status.REFUND).count(),
            'by_prize': by_prize,
        },
        'vouchers': {
            'issued': vouchers.count(),
            'issued_by_source': [
                {'source': r['source'], 'count': r['c']}
                for r in vouchers.values('source').annotate(c=Count('id')).order_by('-c')
            ],
            'redeemed': redeemed.count(),
            'cash_face_redeemed_yen': cash_face_redeemed,
        },
        'risk': {
            'total': risk.count(),
            'open': risk.filter(status=RiskEvent.Status.OPEN).count(),
            'by_type': risk_by_type,
        },
    }
