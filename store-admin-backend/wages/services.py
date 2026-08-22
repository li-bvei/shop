from rest_framework.exceptions import ValidationError

from .models import WageRule


def check_no_period_overlap(employee_id, effective_from, effective_to, exclude_pk=None):
    """Raises if [effective_from, effective_to] would overlap any other
    WageRule period for the same employee. Must be called inside a
    transaction.atomic() block — the queryset is locked with
    select_for_update() so two concurrent requests can't both read "no
    overlap" for periods that do in fact overlap each other."""
    qs = WageRule.objects.select_for_update().filter(employee_id=employee_id)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    for other in qs:
        other_is_open_ended = other.effective_to is None
        this_is_open_ended = effective_to is None
        this_starts_before_other_ends = other_is_open_ended or effective_from <= other.effective_to
        other_starts_before_this_ends = this_is_open_ended or other.effective_from <= effective_to
        if this_starts_before_other_ends and other_starts_before_this_ends:
            raise ValidationError({'effective_from': ['wage-rule-period-overlap']})


def wage_rule_is_locked(wage_rule):
    """True if any locked month's per-day calculation used this rule —
    such a rule must not be edited or deleted through the normal API."""
    from .models import WageMonthlyClosing

    return wage_rule.daily_details.filter(
        result__closing__status=WageMonthlyClosing.Status.LOCKED,
    ).exists()


def check_calculation_freshness(closing):
    """Returns a short reason code if `closing`'s stored results might not
    reflect the current state of ActualWorkRecord/WageRule, else None.
    `confirm` calls this and refuses to proceed on any non-None result —
    a manager must never be able to confirm results that don't reflect an
    attendance edit or rate change made after the last `generate`."""
    from scheduling.models import ActualWorkRecord

    from .calculation import WAGE_CALCULATED_TYPES, month_bounds

    if closing.last_generated_at is None:
        return 'not-generated'

    month_start, month_end = month_bounds(closing.month)
    newer_actual = ActualWorkRecord.objects.filter(
        branch=closing.branch, work_date__gte=month_start, work_date__lte=month_end,
        status__in=[ActualWorkRecord.Status.MANAGER_CONFIRMED, ActualWorkRecord.Status.ADMIN_LOCKED],
        updated_at__gt=closing.last_generated_at,
    ).exists()
    if newer_actual:
        return 'stale-actual-records'

    newer_rule = WageRule.objects.filter(
        employee__branch=closing.branch, employee__employment_type__in=WAGE_CALCULATED_TYPES,
        updated_at__gt=closing.last_generated_at,
    ).exists()
    if newer_rule:
        return 'stale-wage-rule'

    return None
