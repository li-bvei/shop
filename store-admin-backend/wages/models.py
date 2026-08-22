from decimal import Decimal

from django.conf import settings
from django.db import models


class WageRule(models.Model):
    class TransportationType(models.TextChoices):
        NONE = 'none', 'None'
        PER_ATTENDANCE = 'per_attendance', 'Per attendance day'
        MONTHLY = 'monthly', 'Fixed monthly amount'

    employee = models.ForeignKey('staff.StaffMember', on_delete=models.CASCADE, related_name='wage_rules')
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True, help_text='Null means still in effect.')
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=0)
    night_premium_rate = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0.25'))
    overtime_premium_rate = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0.25'))
    statutory_holiday_premium_rate = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0.35'))
    transportation_type = models.CharField(
        max_length=20, choices=TransportationType.choices, default=TransportationType.NONE,
    )
    transportation_amount = models.DecimalField(max_digits=10, decimal_places=0, default=0)
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['employee_id', '-effective_from']

    def __str__(self):
        return f'{self.employee_id} wage rule from {self.effective_from}'


class WageMonthlyClosing(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        CONFIRMED = 'confirmed', 'Confirmed'
        LOCKED = 'locked', 'Locked'

    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE, related_name='wage_monthly_closings')
    month = models.DateField(help_text='Always stored as the 1st of the target month.')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    last_generated_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Set every time `generate` successfully (re)computes results. `confirm` refuses to run if this '
                   'is null (never generated) or older than the newest relevant ActualWorkRecord/WageRule change, '
                   'so a manager can never confirm stale or empty results without first re-generating.',
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    locked_at = models.DateTimeField(null=True, blank=True)
    unlocked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    unlocked_at = models.DateTimeField(null=True, blank=True)
    unlock_reason = models.TextField(blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['branch', 'month'], name='unique_wage_closing_per_branch_month'),
        ]
        ordering = ['-month', 'branch_id']

    def __str__(self):
        return f'{self.branch_id} {self.month:%Y-%m} [{self.status}]'


class WageEmployeeResult(models.Model):
    closing = models.ForeignKey(WageMonthlyClosing, on_delete=models.CASCADE, related_name='employee_results')
    employee = models.ForeignKey('staff.StaffMember', on_delete=models.PROTECT, related_name='wage_results')
    employment_type = models.CharField(max_length=20, help_text='Snapshot of the employee type at generation time.')
    attendance_days = models.PositiveIntegerField(default=0)
    total_minutes = models.PositiveIntegerField(default=0)
    # regular/night/overtime/statutory_holiday_minutes and the three premium
    # amount fields below are v1-only — v2_simple (the current engine,
    # see wages/calculation.py) never populates them; they stay in the
    # schema purely so historical v1 locked results keep displaying
    # correctly, and are never read by anything else.
    regular_minutes = models.PositiveIntegerField(default=0)
    night_minutes = models.PositiveIntegerField(default=0)
    overtime_minutes = models.PositiveIntegerField(default=0)
    statutory_holiday_minutes = models.PositiveIntegerField(default=0)
    base_amount = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    night_premium = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    overtime_premium = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    holiday_premium = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    transportation_amount = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    # v1-only manual adjustment channel — v2_simple uses the dedicated
    # bonus_* fields below instead (see class docstring below).
    manual_addition = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    manual_deduction = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    adjustment_reason = models.TextField(blank=True)
    estimated_total = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    wage_rule_snapshot = models.JSONField(default=dict, blank=True)
    calculation_version = models.CharField(max_length=20, default='v1')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ---- v2_simple fields ---------------------------------------------
    # A manager-entered amount that replaces (not adds to) the
    # WageRule-derived transportation total for this employee this month,
    # e.g. because the employee used a different commute this month. Null
    # means "use the rule's default" (per_attendance sum or flat monthly).
    monthly_transportation_override = models.DecimalField(
        max_digits=12, decimal_places=0, null=True, blank=True,
    )
    # The rule-derived default, always kept up to date by
    # generate_wage_results() regardless of whether an override is
    # currently set — this is what transportation_amount reverts to the
    # instant an override is cleared, with no regenerate needed.
    rule_transportation_amount = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    transportation_override_reason = models.CharField(max_length=255, blank=True)
    transportation_override_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    transportation_override_at = models.DateTimeField(null=True, blank=True)

    # A discretionary bonus for this employee this month — deliberately its
    # own field, not folded into manual_addition, so it reads unambiguously
    # on the payslip and never gets confused with a correction.
    bonus_amount = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    bonus_note = models.CharField(max_length=255, blank=True)
    bonus_updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    bonus_updated_at = models.DateTimeField(null=True, blank=True)

    # An explicit override of the date range generate_wage_results() reads
    # ActualWorkRecord from for this employee this month — for a
    # mid-month departure needing a period other than the automatic
    # [month_start, min(month_end, leave_date)] default. Both null unless
    # an admin/branch has explicitly set them; both must be inside the
    # closing's own month when set.
    calculation_period_start = models.DateField(null=True, blank=True)
    calculation_period_end = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['closing', 'employee'], name='unique_wage_result_per_closing_employee'),
        ]
        ordering = ['closing_id', 'employee_id']

    def __str__(self):
        return f'{self.employee_id} @ {self.closing_id}'


class WageDailyDetail(models.Model):
    """Per-day calculation breakdown, kept even after the parent closing is
    locked — this is what makes a locked month immune to a later WageRule
    edit: every number here is either computed once and stored, or copied
    verbatim from the rule active on that specific day (wage_rule_snapshot)."""

    result = models.ForeignKey(WageEmployeeResult, on_delete=models.CASCADE, related_name='daily_details')
    work_date = models.DateField()
    actual_work_record = models.ForeignKey(
        'scheduling.ActualWorkRecord', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='wage_daily_details',
    )
    wage_rule = models.ForeignKey(
        WageRule, on_delete=models.PROTECT, null=True, blank=True, related_name='daily_details',
    )
    total_minutes = models.PositiveIntegerField(default=0)
    regular_minutes = models.PositiveIntegerField(default=0)
    night_minutes = models.PositiveIntegerField(default=0)
    overtime_minutes = models.PositiveIntegerField(default=0)
    statutory_holiday_minutes = models.PositiveIntegerField(default=0)
    base_amount = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    night_premium = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    overtime_premium = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    holiday_premium = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    transportation_amount = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    wage_rule_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['result', 'work_date'], name='unique_wage_daily_detail_per_result_date'),
        ]
        ordering = ['result_id', 'work_date']

    def __str__(self):
        return f'{self.result_id} {self.work_date}'
