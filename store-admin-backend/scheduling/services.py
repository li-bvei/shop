from datetime import timedelta

from .models import AvailabilityRequest, BranchScheduleSetting, Shift


def seed_default_schedule_setting(branch):
    """Called once from BranchViewSet.perform_create — every branch gets a
    schedule-time template using the model's own field defaults, editable
    afterwards per branch."""
    BranchScheduleSetting.objects.get_or_create(branch=branch)


def _minute_range(work_date, start_time, end_time, crosses_midnight):
    start = work_date.toordinal() * 1440 + start_time.hour * 60 + start_time.minute
    end_day_ordinal = work_date.toordinal() + (1 if crosses_midnight else 0)
    end = end_day_ordinal * 1440 + end_time.hour * 60 + end_time.minute
    return start, end


def check_shift(employee, branch, work_date, planned_start, planned_end, crosses_midnight,
                 planned_break_minutes, period, exclude_pk=None):
    """(hard_errors, soft_warnings) — hard errors always block the save;
    soft warnings only block it if the caller hasn't set override=True."""
    hard_errors = []
    soft_warnings = []

    if planned_start is None or planned_end is None or work_date is None:
        hard_errors.append('shift-invalid-time-range')
        return hard_errors, soft_warnings

    # Data-consistency checks — these are hard errors, never overridable,
    # because they represent a shift that couldn't correspond to a real
    # person working a real shift at a real branch.
    if branch and employee.branch_id != branch.id:
        hard_errors.append('shift-employee-not-in-branch')
    if period is not None and branch and period.branch_id != branch.id:
        hard_errors.append('shift-period-branch-mismatch')
    if period is not None and work_date is not None and not (period.start_date <= work_date <= period.end_date):
        hard_errors.append('shift-date-outside-period')

    start, end = _minute_range(work_date, planned_start, planned_end, crosses_midnight)
    if end <= start:
        hard_errors.append('shift-invalid-time-range')
        return hard_errors, soft_warnings

    duration = end - start
    if planned_break_minutes > duration:
        hard_errors.append('shift-break-exceeds-duration')

    if employee.hire_date and work_date < employee.hire_date:
        hard_errors.append('shift-before-hire-date')
    if employee.leave_date and work_date > employee.leave_date:
        hard_errors.append('shift-after-leave-date')

    # A shift crossing midnight can only ever overlap a neighbour whose own
    # work_date is the day before or after, so that's the full search window.
    window = [work_date - timedelta(days=1), work_date, work_date + timedelta(days=1)]
    candidates = Shift.objects.filter(employee=employee, work_date__in=window)
    if exclude_pk:
        candidates = candidates.exclude(pk=exclude_pk)
    for other in candidates:
        other_start, other_end = _minute_range(
            other.work_date, other.planned_start, other.planned_end, other.crosses_midnight,
        )
        if start < other_end and other_start < end:
            if branch and other.branch_id != branch.id:
                hard_errors.append('shift-overlaps-another-branch')
            else:
                hard_errors.append('shift-overlaps-existing-shift')
            break

    if period is not None:
        availability = AvailabilityRequest.objects.filter(
            period=period, employee=employee, work_date=work_date,
        ).first()
        if availability:
            if availability.availability == AvailabilityRequest.Availability.DAY_OFF:
                soft_warnings.append('shift-conflicts-with-day-off-request')
            elif availability.start_time and availability.end_time:
                avail_start, avail_end = _minute_range(
                    work_date, availability.start_time, availability.end_time, availability.crosses_midnight,
                )
                if start < avail_start or end > avail_end:
                    soft_warnings.append('shift-outside-submitted-availability')

    return hard_errors, soft_warnings
