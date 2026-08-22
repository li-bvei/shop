"""
Wage calculation engine — internal estimation only.

This is explicitly NOT a full labor-law/tax/social-insurance payroll
system. Every generated result and printed PDF carries DISCLAIMER below.
The policy constants and the daily/weekly overtime combination rule are
centralized here so a real deployment can retune them for the actual labor
arrangement in use — if the business actually runs a 変形労働時間制
(modified working-hour system) or any other non-standard scheme, the
thresholds below need to change, and that must be confirmed with the user
first rather than assumed.

Rounding policy (change YEN_ROUNDING_MODE/point below if a different
convention is wanted): each amount component (base/night/overtime/holiday)
is rounded to the nearest yen *per day, per component* — not once at the
end of the month — so every number on a printed daily-detail table is
already the number that was actually summed into the total.

Night/break interaction: the model only stores a *duration* for breaks,
not when during the shift they were taken, so there's no way to know
whether a break fell inside the night window. This engine deducts break
minutes from the non-night portion of the shift first, and only lets the
deduction spill into night minutes once the break exceeds the available
non-night time — i.e. it assumes meal breaks are ordinarily taken during
regular hours unless the whole shift is night hours. Flag this to the user
if actual break timing needs to be tracked more precisely.

Overtime combination (daily >8h and weekly >40h, no double-counting):
for each day, minutes beyond 8h become that day's daily overtime and are
removed from its "regular" pool. Within an ISO week, the *remaining*
regular minutes are accumulated across days in date order; whatever
portion of a day's regular minutes pushes that running weekly total past
40h becomes additional (weekly) overtime, attributed to the day it
happened on. A minute is never counted as overtime twice.
"""
from datetime import time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from scheduling.models import ActualWorkRecord
from staff.models import StaffMember

from .models import WageDailyDetail, WageEmployeeResult, WageRule

NIGHT_START = time(22, 0)
NIGHT_END = time(5, 0)
DAILY_OVERTIME_THRESHOLD_MINUTES = 8 * 60
WEEKLY_OVERTIME_THRESHOLD_MINUTES = 40 * 60
YEN_ROUNDING_POINT = Decimal('1')
YEN_ROUNDING_MODE = ROUND_HALF_UP
# The engine generate_wage_results() actually runs today. v1's
# night/overtime/statutory-holiday premium logic below (classify_minutes,
# split_overtime_within_week) is kept only because historical *locked* v1
# results still reference it for context and existing unit tests exercise
# it directly — it is no longer called by generate_wage_results, which now
# implements the simplified v2_simple formula: base pay = actual minutes /
# 60 * hourly rate, no premiums. See generate_wage_results' docstring.
CALCULATION_VERSION = 'v2_simple'

DISCLAIMER = (
    '临时工／时薪员工工资计算资料，不包含所得税、住民税、社会保险、雇用保险等法定扣除，'
    '不属于最终工资申报结果。'
)

WAGE_CALCULATED_TYPES = (StaffMember.EmploymentType.HOURLY, StaffMember.EmploymentType.TEMPORARY)


def round_yen(value):
    return Decimal(value).quantize(YEN_ROUNDING_POINT, rounding=YEN_ROUNDING_MODE)


def _minute_offset(t, day_offset=0):
    return day_offset * 1440 + t.hour * 60 + t.minute


def _interval_overlap_minutes(a_start, a_end, b_start, b_end):
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def classify_minutes(actual_start, actual_end, crosses_midnight, break_minutes):
    """(total_minutes, night_minutes) for one day's actual attendance."""
    start = _minute_offset(actual_start)
    end = _minute_offset(actual_end, day_offset=1 if crosses_midnight else 0)
    if end <= start:
        return 0, 0

    raw_total = end - start
    night_windows = [
        (_minute_offset(NIGHT_START), _minute_offset(NIGHT_END, day_offset=1)),
        (_minute_offset(NIGHT_START, day_offset=-1), _minute_offset(NIGHT_END, day_offset=0)),
    ]
    raw_night = min(raw_total, sum(_interval_overlap_minutes(start, end, w[0], w[1]) for w in night_windows))
    raw_regular = raw_total - raw_night

    break_from_regular = min(break_minutes, raw_regular)
    break_from_night = break_minutes - break_from_regular

    total_minutes = max(0, raw_total - break_minutes)
    night_minutes = max(0, raw_night - break_from_night)
    return total_minutes, night_minutes


def split_overtime_within_week(day_entries):
    """day_entries: [(work_date, total_minutes), ...] sorted by date, all
    within one ISO week. Returns {work_date: overtime_minutes}."""
    result = {}
    running_regular = 0
    for work_date, total_minutes in day_entries:
        daily_ot = max(0, total_minutes - DAILY_OVERTIME_THRESHOLD_MINUTES)
        day_regular = total_minutes - daily_ot
        weekly_ot = 0
        if running_regular + day_regular > WEEKLY_OVERTIME_THRESHOLD_MINUTES:
            weekly_ot = min(day_regular, running_regular + day_regular - WEEKLY_OVERTIME_THRESHOLD_MINUTES)
        running_regular += day_regular - weekly_ot
        result[work_date] = daily_ot + weekly_ot
    return result


def _iso_week_key(d):
    year, week, _ = d.isocalendar()
    return (year, week)


def select_wage_rule(work_date, rules_sorted_desc):
    for rule in rules_sorted_desc:
        if rule.effective_from <= work_date and (rule.effective_to is None or work_date <= rule.effective_to):
            return rule
    return None


def _rule_snapshot(rule):
    return {
        'hourly_rate': str(rule.hourly_rate),
        'night_premium_rate': str(rule.night_premium_rate),
        'overtime_premium_rate': str(rule.overtime_premium_rate),
        'statutory_holiday_premium_rate': str(rule.statutory_holiday_premium_rate),
        'transportation_type': rule.transportation_type,
        'transportation_amount': str(rule.transportation_amount),
        'effective_from': rule.effective_from.isoformat(),
        'effective_to': rule.effective_to.isoformat() if rule.effective_to else None,
    }


def month_bounds(month_date):
    month_start = month_date.replace(day=1)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return month_start, next_month - timedelta(days=1)


def _default_period_end(employee, month_start, month_end):
    """A mid-month leave_date caps the default calculation window — an
    employee can't have real confirmed attendance after they've left, but
    this is a defensive, explicit cap in case data ever says otherwise."""
    if employee.leave_date and month_start <= employee.leave_date <= month_end:
        return min(month_end, employee.leave_date)
    return month_end


@transaction.atomic
def generate_wage_results(closing):
    """(Re)computes every WageEmployeeResult + WageDailyDetail for a draft
    WageMonthlyClosing from ActualWorkRecord (never from Shift — a plan is
    not attendance). v2_simple formula: base pay = actual worked minutes
    (actual_end - actual_start - actual_break_minutes) / 60 * hourly rate;
    no night/overtime/statutory-holiday premiums. Only hourly/temporary
    employees ever get a nonzero wage amount — regular_monthly still gets
    a result row (so its hours are visible) but always at zero pay.

    Idempotent and *non-destructive* on manager-entered fields: re-running
    this (e.g. after new attendance gets confirmed) updates each row's
    auto-derived numbers (hours, base_amount, rule-derived transportation)
    via get_or_create per employee, but never touches
    monthly_transportation_override / bonus_amount / bonus_note /
    calculation_period_start / calculation_period_end — those persist
    across regeneration exactly as WageEmployeeResultViewSet.perform_update
    last saved them. An employee whose confirmed attendance has since
    dropped to zero (e.g. records got un-confirmed) still has their row
    recomputed down to zero hours, not silently left stale.

    Days where an hourly/temporary employee has no matching WageRule still
    get a zero-amount detail row (wage_rule=None) so the gap is visible in
    the draft; WageMonthlyClosingViewSet.confirm blocks on any such row
    before allowing confirmation."""
    branch = closing.branch
    month_start, month_end = month_bounds(closing.month)

    confirmed_records = list(
        ActualWorkRecord.objects.filter(
            branch=branch, work_date__gte=month_start, work_date__lte=month_end, absent=False,
            status__in=[ActualWorkRecord.Status.MANAGER_CONFIRMED, ActualWorkRecord.Status.ADMIN_LOCKED],
        ).select_related('employee').order_by('employee_id', 'work_date')
    )
    by_employee = {}
    for r in confirmed_records:
        by_employee.setdefault(r.employee_id, []).append(r)

    existing_results = {r.employee_id: r for r in closing.employee_results.select_related('employee').all()}
    # The simple monthly table must list every active hourly/temporary
    # employee even when they have zero confirmed attendance, so a missing
    # hourly rate is visible before confirmation instead of silently hiding
    # the employee from payroll.
    employees = {
        e.id: e for e in StaffMember.objects.filter(
            branch=branch, status=StaffMember.Status.ACTIVE,
            employment_type__in=WAGE_CALCULATED_TYPES,
        )
    }
    for employee_id, result in existing_results.items():
        employees.setdefault(employee_id, result.employee)

    rules_by_employee = {}
    for rule in WageRule.objects.filter(employee_id__in=employees.keys()).order_by('employee_id', '-effective_from'):
        rules_by_employee.setdefault(rule.employee_id, []).append(rule)

    for employee_id, employee in employees.items():
        result = existing_results.get(employee_id)
        if result is None:
            result = WageEmployeeResult.objects.create(
                closing=closing, employee=employee, employment_type=employee.employment_type,
                calculation_version=CALCULATION_VERSION,
            )

        period_start = result.calculation_period_start or month_start
        period_end = result.calculation_period_end or _default_period_end(employee, month_start, month_end)
        emp_records = [
            r for r in by_employee.get(employee_id, []) if period_start <= r.work_date <= period_end
        ]
        emp_rules = rules_by_employee.get(employee_id, [])
        needs_rule = employee.employment_type in WAGE_CALCULATED_TYPES

        result.daily_details.all().delete()

        attendance_days = 0
        total_minutes_sum = 0
        base_total = Decimal(0)
        rule_transportation_total = Decimal(0)
        last_used_rule = None

        for r in emp_records:
            if r.actual_start is None or r.actual_end is None:
                continue
            total, _night = classify_minutes(r.actual_start, r.actual_end, r.crosses_midnight, r.actual_break_minutes)

            rule = select_wage_rule(r.work_date, emp_rules) if needs_rule else None
            base = Decimal(0)
            day_transportation = Decimal(0)
            snapshot = {}
            if needs_rule and rule is not None:
                last_used_rule = rule
                base = round_yen(Decimal(total) / 60 * rule.hourly_rate)
                if rule.transportation_type == WageRule.TransportationType.PER_ATTENDANCE:
                    day_transportation = rule.transportation_amount
                snapshot = _rule_snapshot(rule)

            attendance_days += 1
            total_minutes_sum += total
            base_total += base
            rule_transportation_total += day_transportation

            WageDailyDetail.objects.create(
                result=result, work_date=r.work_date, actual_work_record=r, wage_rule=rule,
                total_minutes=total, regular_minutes=total, night_minutes=0, overtime_minutes=0,
                statutory_holiday_minutes=0, base_amount=base, night_premium=0, overtime_premium=0,
                holiday_premium=0, transportation_amount=day_transportation, wage_rule_snapshot=snapshot,
            )

        if needs_rule:
            default_rule = last_used_rule or select_wage_rule(period_end, emp_rules)
            if default_rule and default_rule.transportation_type == WageRule.TransportationType.MONTHLY:
                rule_transportation_total += default_rule.transportation_amount

        transportation_amount = (
            result.monthly_transportation_override
            if result.monthly_transportation_override is not None
            else rule_transportation_total
        )

        result.rule_transportation_amount = rule_transportation_total
        result.employment_type = employee.employment_type
        result.calculation_version = CALCULATION_VERSION
        result.attendance_days = attendance_days
        result.total_minutes = total_minutes_sum
        result.regular_minutes = total_minutes_sum
        result.night_minutes = 0
        result.overtime_minutes = 0
        result.statutory_holiday_minutes = 0
        result.base_amount = base_total
        result.night_premium = Decimal(0)
        result.overtime_premium = Decimal(0)
        result.holiday_premium = Decimal(0)
        result.transportation_amount = transportation_amount
        result.estimated_total = base_total + transportation_amount + result.bonus_amount
        result.save()


def find_missing_wage_rule_days(closing):
    """[(employee_name, work_date), ...] for every hourly/temporary
    employee-day in this closing with no matching WageRule — confirming a
    closing while this is non-empty is blocked by the view layer."""
    gaps = (
        WageDailyDetail.objects
        .filter(result__closing=closing, wage_rule__isnull=True, result__employment_type__in=WAGE_CALCULATED_TYPES)
        .select_related('result__employee')
        .order_by('result__employee__name', 'work_date')
    )
    return [(detail.result.employee.name, detail.work_date) for detail in gaps]
