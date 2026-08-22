"""
Monthly business analysis — real aggregation plus a deterministic,
rule-based "automatic analysis" pass. No external AI is used anywhere in
this module; every finding is a fixed threshold check against real numbers,
and every finding states the rule, the threshold, and the actual value so
it's auditable rather than a black box.

Terminology guardrails (do not relax these without the user's explicit
sign-off — see the project spec this module was built against):
  - "暂定经营差额" is revenue minus purchasing minus expenses minus hourly/
    temp wages. It is NOT profit (it excludes rent, utilities, regular-
    salaried payroll, depreciation, tax, etc.) and must never be labeled
    "利润" anywhere in the API or the frontend that renders it.
  - The purchasing/revenue ratio is not "毛利率" (gross margin) — it only
    covers ingredient/goods purchasing, not all cost of goods sold.
  - The wages/revenue ratio is not a full labor-cost ratio — it only
    covers hourly/temporary wages, excluding regular-salaried payroll.
  - Anomaly findings use neutral wording ("建议确认" / "与通常数据差异较
    大") — never words implying wrongdoing.

Thresholds are centralized as module constants below so they can be
retuned without touching the aggregation logic itself.
"""
from collections import defaultdict
from datetime import date as date_cls
from datetime import timedelta
from decimal import Decimal

from dailyreports.models import DailyReport, DailyReportHistory
from paymentmethods.models import PaymentMethodDef
from purchasing.models import PurchaseRecord
from wages.models import WageEmployeeResult, WageMonthlyClosing

# ---- Centralized, retunable thresholds -------------------------------------

MIN_SAMPLE_SIZE_FOR_TREND_ANALYSIS = 5
ANOMALY_DEVIATION_THRESHOLD_PCT = Decimal('40')  # flag a day this far from the monthly average
HISTORY_HEAVY_EDIT_THRESHOLD = 3  # "modified several times" starting at this count
WEEKDAY_NAMES_ZH = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
WEEKDAY_NAMES_JA = ['月曜', '火曜', '水曜', '木曜', '金曜', '土曜', '日曜']


def _d(value):
    """Decimal-safe conversion — JSON-sourced amounts must go through
    Decimal(str(value)), never Decimal(float) or plain float arithmetic."""
    if value is None:
        return Decimal('0')
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def month_bounds(year, month):
    start = date_cls(year, month, 1)
    next_start = date_cls(year + 1, 1, 1) if month == 12 else date_cls(year, month + 1, 1)
    return start, next_start - timedelta(days=1)


def previous_month(year, month):
    """January's previous month is correctly December of the prior year."""
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _pct_delta(curr, prev):
    if not prev:
        return None
    return round(float((curr - prev) / prev * 100), 1)


def _payment_method_breakdown(reports):
    """Sums DailyReport.payment_amounts (keyed by the real PaymentMethodDef
    id, per the established convention) across the given reports."""
    totals = defaultdict(Decimal)
    for report in reports:
        for method_id, amount in (report.payment_amounts or {}).items():
            totals[method_id] += _d(amount)
    return totals


def _expense_total(reports):
    total = Decimal('0')
    for report in reports:
        for expense in report.expenses or []:
            total += _d(expense.get('amount'))
    return total


def _weekday_averages(reports_by_date):
    buckets = defaultdict(list)
    for d, revenue in reports_by_date.items():
        buckets[d.weekday()].append(revenue)
    return {
        wd: (sum(values) / len(values) if values else None)
        for wd, values in buckets.items()
    }


def build_monthly_analysis(*, branch_ids, year, month, is_admin_all_branches):
    """branch_ids: list of Branch ids to include (a single id for a scoped
    view, or every branch's id for admin's all-branches view)."""
    month_start, month_end = month_bounds(year, month)
    prev_year, prev_month = previous_month(year, month)
    prev_start, prev_end = month_bounds(prev_year, prev_month)

    reports_qs = DailyReport.objects.filter(branch_id__in=branch_ids, date__gte=month_start, date__lte=month_end)
    reports = list(reports_qs.order_by('date'))
    prev_reports = list(
        DailyReport.objects.filter(branch_id__in=branch_ids, date__gte=prev_start, date__lte=prev_end)
    )

    revenue = sum((_d(r.total_revenue) for r in reports), Decimal('0'))
    customers = sum((r.total_customers or 0) for r in reports)
    prev_revenue = sum((_d(r.total_revenue) for r in prev_reports), Decimal('0'))
    prev_customers = sum((r.total_customers or 0) for r in prev_reports)

    avg_spend = round_avg(revenue, customers)
    prev_avg_spend = round_avg(prev_revenue, prev_customers)

    purchases_qs = PurchaseRecord.objects.filter(branch_id__in=branch_ids, date__gte=month_start, date__lte=month_end)
    prev_purchases_qs = PurchaseRecord.objects.filter(
        branch_id__in=branch_ids, date__gte=prev_start, date__lte=prev_end,
    )
    purchasing_total = sum((_d(p.amount) for p in purchases_qs), Decimal('0'))
    prev_purchasing_total = sum((_d(p.amount) for p in prev_purchases_qs), Decimal('0'))

    expense_total = _expense_total(reports)

    # Wages: whichever WageMonthlyClosing exists for this month/branch set —
    # locked uses the frozen numbers, anything else is shown as tentative.
    closings = list(
        WageMonthlyClosing.objects.filter(branch_id__in=branch_ids, month=month_start)
        .prefetch_related('employee_results')
    )
    wage_total = Decimal('0')
    wage_status = 'not_generated'
    if closings:
        statuses = {c.status for c in closings}
        if statuses == {WageMonthlyClosing.Status.LOCKED}:
            wage_status = 'locked'
        elif WageMonthlyClosing.Status.LOCKED in statuses:
            wage_status = 'partially_locked'
        elif WageMonthlyClosing.Status.CONFIRMED in statuses:
            wage_status = 'confirmed'
        else:
            wage_status = 'draft'
        for closing in closings:
            for result in closing.employee_results.all():
                wage_total += _d(result.estimated_total)

    tentative_operating_gap = revenue - purchasing_total - expense_total - wage_total

    reports_by_date = {r.date: _d(r.total_revenue) for r in reports}
    customers_by_date = {r.date: (r.total_customers or 0) for r in reports}
    days_with_reports = len(reports)
    daily_average_revenue = (revenue / days_with_reports) if days_with_reports else Decimal('0')

    highest_day = max(reports_by_date.items(), key=lambda kv: kv[1]) if reports_by_date else None
    lowest_day = min(reports_by_date.items(), key=lambda kv: kv[1]) if reports_by_date else None

    daily_trend = [
        {
            'date': r.date.isoformat(),
            'revenue': str(_d(r.total_revenue)),
            'customers': r.total_customers,
            'avgSpend': str(round_avg(_d(r.total_revenue), r.total_customers)),
            'purchasing': str(sum(
                (_d(p.amount) for p in purchases_qs if p.date == r.date), Decimal('0'),
            )),
        }
        for r in reports
    ]

    payment_breakdown = _payment_method_breakdown(reports)

    supplier_totals = defaultdict(Decimal)
    supplier_names = {}
    for p in purchases_qs.select_related('supplier'):
        supplier_totals[p.supplier_id] += _d(p.amount)
        supplier_names[p.supplier_id] = p.supplier.name
    supplier_ranking = sorted(
        (
            {'supplierId': sid, 'supplierName': supplier_names[sid], 'amount': str(amount)}
            for sid, amount in supplier_totals.items()
        ),
        key=lambda row: Decimal(row['amount']), reverse=True,
    )

    weekday_avg = _weekday_averages(reports_by_date)
    weekday_rows = [
        {
            'weekday': wd,
            'nameZh': WEEKDAY_NAMES_ZH[wd],
            'nameJa': WEEKDAY_NAMES_JA[wd],
            'averageRevenue': str(_d(weekday_avg.get(wd)).quantize(Decimal('1'))) if weekday_avg.get(wd) is not None else None,
        }
        for wd in range(7)
    ]

    history_counts = defaultdict(int)
    for h in DailyReportHistory.objects.filter(branch_id__in=branch_ids, date__gte=month_start, date__lte=month_end):
        history_counts[h.date] += 1

    daily_detail = [
        {
            'date': r.date.isoformat(),
            'branchId': r.branch_id,
            'revenue': str(_d(r.total_revenue)),
            'customers': r.total_customers,
            'avgSpend': str(round_avg(_d(r.total_revenue), r.total_customers)),
            'editCount': history_counts.get(r.date, 0),
        }
        for r in reports
    ]

    branch_comparison = None
    if is_admin_all_branches:
        branch_comparison = _branch_comparison(branch_ids, month_start, month_end, prev_start, prev_end)

    result = {
        'month': month_start.isoformat()[:7],
        'revenue': str(revenue), 'previousRevenue': str(prev_revenue), 'revenueDeltaPct': _pct_delta(revenue, prev_revenue),
        'customers': customers, 'previousCustomers': prev_customers, 'customersDeltaPct': _pct_delta(customers, prev_customers),
        'avgSpend': str(avg_spend), 'previousAvgSpend': str(prev_avg_spend), 'avgSpendDeltaPct': _pct_delta(avg_spend, prev_avg_spend),
        'purchasing': str(purchasing_total), 'previousPurchasing': str(prev_purchasing_total),
        'purchasingDeltaPct': _pct_delta(purchasing_total, prev_purchasing_total),
        'expenses': str(expense_total),
        'wageTotal': str(wage_total), 'wageStatus': wage_status,
        'tentativeOperatingGap': str(tentative_operating_gap),
        'daysWithReports': days_with_reports,
        'dailyAverageRevenue': str(daily_average_revenue),
        'highestRevenueDay': {'date': highest_day[0].isoformat(), 'revenue': str(highest_day[1])} if highest_day else None,
        'lowestRevenueDay': {'date': lowest_day[0].isoformat(), 'revenue': str(lowest_day[1])} if lowest_day else None,
        'dailyTrend': daily_trend,
        'paymentMethodBreakdown': [
            {'paymentMethodId': mid, 'amount': str(amount)} for mid, amount in payment_breakdown.items()
        ],
        'supplierRanking': supplier_ranking,
        'weekdayAverages': weekday_rows,
        'branchComparison': branch_comparison,
        'dailyDetail': daily_detail,
    }
    payment_method_names = {
        str(m.id): (m.custom_name or m.code)
        for m in PaymentMethodDef.objects.filter(id__in=payment_breakdown.keys())
    }
    result['insights'] = build_insights(
        result, reports_by_date, customers_by_date, branch_comparison, payment_breakdown, supplier_ranking,
        history_counts, revenue, purchasing_total, wage_total, payment_method_names,
    )
    return result


def round_avg(revenue, customers):
    if not customers:
        return Decimal('0')
    return (revenue / customers).quantize(Decimal('1'))


def _branch_comparison(branch_ids, month_start, month_end, prev_start, prev_end):
    from branches.models import Branch

    rows = []
    for branch in Branch.objects.filter(id__in=branch_ids):
        cur = sum(
            (_d(r.total_revenue) for r in DailyReport.objects.filter(
                branch=branch, date__gte=month_start, date__lte=month_end,
            )), Decimal('0'),
        )
        prev = sum(
            (_d(r.total_revenue) for r in DailyReport.objects.filter(
                branch=branch, date__gte=prev_start, date__lte=prev_end,
            )), Decimal('0'),
        )
        rows.append({
            'branchId': branch.id, 'revenue': str(cur), 'previousRevenue': str(prev),
            'deltaPct': _pct_delta(cur, prev),
        })
    return rows


def build_insights(summary, reports_by_date, customers_by_date, branch_comparison,
                    payment_breakdown, supplier_ranking, history_counts, revenue, purchasing_total, wage_total,
                    payment_method_names=None):
    """Deterministic, rule-based findings only — no external AI. Each
    finding carries the rule name, the threshold used, and the actual
    value, so every claim is independently checkable."""
    insights = []

    if summary['revenueDeltaPct'] is not None:
        insights.append({
            'rule': 'revenue_mom_change', 'severity': 'info',
            'message': f"本月营业额较上月{'增长' if summary['revenueDeltaPct'] >= 0 else '下降'}{abs(summary['revenueDeltaPct'])}%",
            'threshold': None, 'value': summary['revenueDeltaPct'],
        })
        if summary['customersDeltaPct'] is not None and summary['avgSpendDeltaPct'] is not None:
            closer_to_customers = abs(summary['customersDeltaPct'] - summary['revenueDeltaPct']) <= \
                abs(summary['avgSpendDeltaPct'] - summary['revenueDeltaPct'])
            insights.append({
                'rule': 'revenue_change_driver', 'severity': 'info',
                'message': f"营业额变化更接近{'客数' if closer_to_customers else '客单价'}的变化幅度",
                'threshold': None, 'value': None,
            })

    if len(reports_by_date) < MIN_SAMPLE_SIZE_FOR_TREND_ANALYSIS:
        insights.append({
            'rule': 'insufficient_sample', 'severity': 'info',
            'message': f'本月有日报天数不足{MIN_SAMPLE_SIZE_FOR_TREND_ANALYSIS}天，数据不足，暂不判断趋势类异常',
            'threshold': MIN_SAMPLE_SIZE_FOR_TREND_ANALYSIS, 'value': len(reports_by_date),
        })
    else:
        values = list(reports_by_date.values())
        mean = sum(values, Decimal('0')) / len(values)
        if mean > 0:
            for d, v in reports_by_date.items():
                deviation_pct = abs(v - mean) / mean * 100
                if deviation_pct >= ANOMALY_DEVIATION_THRESHOLD_PCT:
                    insights.append({
                        'rule': 'revenue_deviation_from_monthly_average', 'severity': 'notice',
                        'message': f"{d.isoformat()} 营业额与本月日均相比差异较大，建议确认",
                        'threshold': float(ANOMALY_DEVIATION_THRESHOLD_PCT), 'value': round(float(deviation_pct), 1),
                    })

    if summary['highestRevenueDay']:
        insights.append({
            'rule': 'highest_revenue_day', 'severity': 'info',
            'message': f"本月营业额最高日为 {summary['highestRevenueDay']['date']}（¥{summary['highestRevenueDay']['revenue']}）",
            'threshold': None, 'value': None,
        })
    if summary['lowestRevenueDay']:
        insights.append({
            'rule': 'lowest_revenue_day', 'severity': 'info',
            'message': f"本月营业额最低日为 {summary['lowestRevenueDay']['date']}（¥{summary['lowestRevenueDay']['revenue']}）",
            'threshold': None, 'value': None,
        })

    weekday_rows = [r for r in summary['weekdayAverages'] if r['averageRevenue'] is not None]
    if weekday_rows:
        best = max(weekday_rows, key=lambda r: Decimal(r['averageRevenue']))
        worst = min(weekday_rows, key=lambda r: Decimal(r['averageRevenue']))
        insights.append({
            'rule': 'best_worst_weekday', 'severity': 'info',
            'message': f"平均营业额最高的星期为{best['nameZh']}，最低为{worst['nameZh']}",
            'threshold': None, 'value': None,
        })

    if revenue > 0:
        purchasing_ratio = round(float(purchasing_total / revenue * 100), 1)
        insights.append({
            'rule': 'purchasing_to_revenue_ratio', 'severity': 'info',
            'message': f'本月进货额占营业额约{purchasing_ratio}%',
            'threshold': None, 'value': purchasing_ratio,
        })
        if wage_total > 0:
            wage_ratio = round(float(wage_total / revenue * 100), 1)
            insights.append({
                'rule': 'hourly_wage_to_revenue_ratio', 'severity': 'info',
                'message': f'本月临时工/时薪工资占营业额约{wage_ratio}%',
                'threshold': None, 'value': wage_ratio,
            })

    if branch_comparison:
        with_revenue = [r for r in branch_comparison if Decimal(r['revenue']) > 0]
        if with_revenue:
            top = max(with_revenue, key=lambda r: Decimal(r['revenue']))
            insights.append({
                'rule': 'top_branch_by_revenue', 'severity': 'info',
                'message': f"本月营业额最高的分店为 {top['branchId']}",
                'threshold': None, 'value': None,
            })
        with_delta = [r for r in branch_comparison if r['deltaPct'] is not None]
        if with_delta:
            biggest_change = max(with_delta, key=lambda r: abs(r['deltaPct']))
            insights.append({
                'rule': 'branch_with_largest_change', 'severity': 'info',
                'message': f"环比变化最大的分店为 {biggest_change['branchId']}（{biggest_change['deltaPct']}%）",
                'threshold': None, 'value': biggest_change['deltaPct'],
            })

    if payment_breakdown:
        top_method = max(payment_breakdown.items(), key=lambda kv: kv[1])
        method_name = (payment_method_names or {}).get(top_method[0], str(top_method[0]))
        insights.append({
            'rule': 'top_payment_method', 'severity': 'info',
            'message': f"占比最高的支付方式为 {method_name}",
            'threshold': None, 'value': None,
        })

    if supplier_ranking:
        insights.append({
            'rule': 'top_supplier_by_purchasing', 'severity': 'info',
            'message': f"本月进货额最高的供应商为 {supplier_ranking[0]['supplierName']}",
            'threshold': None, 'value': None,
        })

    heavy_edits = [(d, c) for d, c in history_counts.items() if c >= HISTORY_HEAVY_EDIT_THRESHOLD]
    for d, c in sorted(heavy_edits):
        insights.append({
            'rule': 'daily_report_heavily_edited', 'severity': 'notice',
            'message': f"{d.isoformat()} 的日报当日修改了 {c} 次，建议确认",
            'threshold': HISTORY_HEAVY_EDIT_THRESHOLD, 'value': c,
        })

    return insights
