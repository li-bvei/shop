from datetime import time

from django.conf import settings
from django.db import models


class BranchScheduleSetting(models.Model):
    """Per-branch shift-time template for the monthly schedule grid's
    four cell states (off/morning/afternoon/full-day). Defaults match the
    Organization's existing three branches (心斋桥/难波/梅田) as of this
    phase, but are independently editable per branch — a future customer's
    branch is never forced onto these specific hours, only seeded with
    them as a reasonable starting point (BranchViewSet.perform_create).
    Paid hours per cell are always derived from these times minus the
    break, never stored separately, so there's exactly one source of
    truth: morning=4.5h, afternoon=5h, full-day=9.5h (11.5h span minus a
    120-minute break) with the current defaults."""

    branch = models.OneToOneField('branches.Branch', on_delete=models.CASCADE, related_name='schedule_setting')
    morning_start = models.TimeField(default=time(10, 30))
    morning_end = models.TimeField(default=time(15, 0))
    afternoon_start = models.TimeField(default=time(17, 0))
    afternoon_end = models.TimeField(default=time(22, 0))
    full_day_start = models.TimeField(default=time(10, 30))
    full_day_end = models.TimeField(default=time(22, 0))
    full_day_break_start = models.TimeField(default=time(15, 0))
    full_day_break_end = models.TimeField(default=time(17, 0))
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.branch_id} schedule setting'


class SchedulePeriod(models.Model):
    class Status(models.TextChoices):
        COLLECTING = 'collecting', 'Collecting availability'
        DRAFTING = 'drafting', 'Drafting shifts'
        PUBLISHED = 'published', 'Published'
        CLOSED = 'closed', 'Closed'

    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE, related_name='schedule_periods')
    # Always the 1st of the month for the current month-based flow — a
    # period is now created by picking branch+month, never by typing
    # start/end dates by hand (SchedulePeriodSerializer computes start_date/
    # end_date from this and rejects client-submitted dates). NULL only for
    # legacy periods created before this phase, which keep their original
    # arbitrary start_date/end_date and stay read-only historical data —
    # never migrated, never deleted.
    month = models.DateField(null=True, blank=True)
    start_date = models.DateField(help_text='Server-computed from `month` for current periods; a legacy period '
                                              'may have any arbitrary range, including ones crossing month bounds.')
    end_date = models.DateField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.COLLECTING)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    version = models.PositiveIntegerField(default=1)
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_date', 'branch_id']
        # MySQL permits multiple NULL values in an ordinary UNIQUE index,
        # so legacy month=NULL rows remain valid while current monthly rows
        # are protected against concurrent duplicate creation.
        constraints = [
            models.UniqueConstraint(fields=['branch', 'month'], name='unique_schedule_period_per_branch_month'),
        ]

    def __str__(self):
        return f'{self.branch_id} {self.start_date}~{self.end_date}'


class AvailabilityRequest(models.Model):
    class Availability(models.TextChoices):
        AVAILABLE = 'available', 'Available'
        DAY_OFF = 'day_off', 'Day off requested'

    period = models.ForeignKey(SchedulePeriod, on_delete=models.CASCADE, related_name='availability_requests')
    employee = models.ForeignKey('staff.StaffMember', on_delete=models.CASCADE, related_name='availability_requests')
    work_date = models.DateField()
    availability = models.CharField(max_length=10, choices=Availability.choices)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    crosses_midnight = models.BooleanField(default=False)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['period', 'employee', 'work_date'], name='unique_availability_per_period_employee_date',
            ),
        ]
        ordering = ['period_id', 'employee_id', 'work_date']

    def __str__(self):
        return f'{self.employee_id} {self.work_date} {self.availability}'


class Shift(models.Model):
    period = models.ForeignKey(SchedulePeriod, on_delete=models.CASCADE, related_name='shifts')
    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE, related_name='shifts')
    employee = models.ForeignKey('staff.StaffMember', on_delete=models.CASCADE, related_name='shifts')
    work_date = models.DateField()
    planned_start = models.TimeField()
    planned_end = models.TimeField()
    crosses_midnight = models.BooleanField(default=False)
    planned_break_minutes = models.PositiveIntegerField(default=0)
    position = models.CharField(max_length=100, blank=True)
    note = models.CharField(max_length=255, blank=True)
    # A manager can force-save past a soft warning (assigned on the
    # employee's requested day off, or outside their submitted available
    # hours) — when they do, this trio records that it happened, by whom,
    # and why, instead of silently overwriting the warning.
    override = models.BooleanField(default=False)
    override_reason = models.CharField(max_length=255, blank=True)
    override_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    override_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['work_date', 'branch_id', 'planned_start']

    def __str__(self):
        return f'{self.employee_id} {self.work_date} {self.planned_start}-{self.planned_end}'


class ActualWorkRecord(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending manager confirmation'
        MANAGER_CONFIRMED = 'manager_confirmed', 'Confirmed by branch manager'
        ADMIN_LOCKED = 'admin_locked', 'Locked by admin'

    shift = models.ForeignKey(
        Shift, on_delete=models.SET_NULL, null=True, blank=True, related_name='actual_work_records',
        help_text='Null for an attendance that was never scheduled (walk-in temp coverage, etc).',
    )
    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE, related_name='actual_work_records')
    employee = models.ForeignKey('staff.StaffMember', on_delete=models.CASCADE, related_name='actual_work_records')
    work_date = models.DateField()
    actual_start = models.TimeField(null=True, blank=True)
    actual_end = models.TimeField(null=True, blank=True)
    crosses_midnight = models.BooleanField(default=False)
    actual_break_minutes = models.PositiveIntegerField(default=0)
    absent = models.BooleanField(default=False)
    # Never inferred — true only when a branch manager explicitly marks a
    # date as a statutory holiday; wage calculation trusts this flag as-is.
    statutory_holiday = models.BooleanField(default=False)
    adjustment_reason = models.CharField(
        max_length=255, blank=True,
        help_text='Required whenever actual times differ from the shift they were generated from.',
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['employee', 'work_date'], name='unique_actual_work_per_employee_date'),
        ]
        ordering = ['work_date', 'branch_id', 'employee_id']

    def __str__(self):
        return f'{self.employee_id} {self.work_date} [{self.status}]'
