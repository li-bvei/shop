from django.conf import settings
from django.db import models


class BranchScheduleSetting(models.Model):
    """Per-branch attendance rules: grace minutes, the business-day
    cutover hour and whether employees may clock themselves in.

    Shift TIMES no longer live here. Until migration 0011 this model held
    a fixed morning / afternoon / full-day template and the schedule grid
    could only ever place one of those three slots; they are now ordinary
    rows of ShiftTemplate, of which a branch may have any number, each
    with its own start, end and break (see ShiftTemplate)."""

    branch = models.OneToOneField('branches.Branch', on_delete=models.CASCADE, related_name='schedule_setting')
    active = models.BooleanField(default=True)

    # --- Attendance (clock-in/out) policy --------------------------------
    # Grace before a punch counts as late / early, in minutes. Both
    # reference projects make this configurable rather than fixed (Frappe
    # HR: late_entry_grace_period / early_exit_grace_period on Shift Type;
    # Horilla: a GraceTime record), because a minute's tolerance is a
    # business decision, not a technical one. Default 0 = no tolerance,
    # which is the honest default: a branch that wants slack opts into it.
    late_grace_minutes = models.PositiveSmallIntegerField(default=0)
    early_leave_grace_minutes = models.PositiveSmallIntegerField(default=0)
    # The hour of day at which one business day's attendance ends and the
    # next begins. A punch before this hour belongs to the PREVIOUS
    # business date, which is what makes a 01:30 clock-out from a 22:00
    # shift land on the right day (and on the right wage month, at a month
    # boundary). 5 fits this chain's existing latest closing time of 22:00
    # with room for overrun; it is per branch because a branch that opens
    # earlier needs a different one.
    attendance_day_cutover_hour = models.PositiveSmallIntegerField(default=5)
    # Whether employees of this branch may clock themselves in and out.
    # Off = attendance stays manager-entered exactly as before this
    # feature existed, so a branch can adopt self-service when it's ready
    # rather than being switched over by a deployment.
    self_punch_enabled = models.BooleanField(default=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.branch_id} schedule setting'


class ShiftTemplate(models.Model):
    """A named, reusable shift time — the branch's palette for the
    schedule grid ("早番 09:00-14:00", "ラスト 18:00-23:30", ...).

    Modelled on Frappe HR's Shift Type (start_time, end_time, a roster
    colour, assigned to employees per date), which is the time-based
    shape every general-purpose scheduler studied shares — Horilla's
    EmployeeShiftSchedule and MASTERPLAN's Service are the same idea. As
    in Frappe, a template whose end is not after its start runs past
    midnight (a 22:00-02:00 template ends on the next day); there is no
    separate flag to keep in step with the times.

    Unlike Frappe, which links an assignment to its Shift Type and reads
    the times live, a Shift COPIES the template's times when it is placed
    and keeps only a reference for its label and colour. Editing or
    deleting a template therefore never rewrites a schedule that has
    already been planned, worked or paid; it only changes what the next
    click places. See docs/ai-handoff/09_SCHEDULING.md."""

    class Color(models.TextChoices):
        BLUE = 'blue', 'Blue'
        GREEN = 'green', 'Green'
        ORANGE = 'orange', 'Orange'
        PURPLE = 'purple', 'Purple'
        RED = 'red', 'Red'
        TEAL = 'teal', 'Teal'
        GRAY = 'gray', 'Gray'

    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE, related_name='shift_templates')
    # Optional: an unnamed template is shown by its times, which is also
    # how the templates migrated from the old three fixed slots appear.
    name = models.CharField(max_length=40, blank=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    break_minutes = models.PositiveIntegerField(default=0)
    color = models.CharField(max_length=10, choices=Color.choices, default=Color.BLUE)
    sort_order = models.PositiveSmallIntegerField(default=0)
    # Retired templates stay so the shifts that reference them keep their
    # label, but are no longer offered in the grid.
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['branch_id', 'sort_order', 'start_time', 'id']

    @property
    def crosses_midnight(self):
        return self.end_time <= self.start_time

    def __str__(self):
        label = self.name or f'{self.start_time:%H:%M}-{self.end_time:%H:%M}'
        return f'{self.branch_id} {label}'


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
    # The template this shift was placed from, if any — for its label and
    # colour only. The times above are the shift's own copy and are what
    # attendance and wages are measured against.
    template = models.ForeignKey(
        ShiftTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name='shifts',
    )
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

    class Source(models.TextChoices):
        PLAN = 'plan', 'Generated from the published schedule'
        PUNCH = 'punch', 'Derived from the employee\'s clock punches'
        MANUAL = 'manual', 'Entered or edited directly by a manager'
        CORRECTION = 'correction', 'Set by an approved correction request'

    # Where this day's times came from. Visible in the manager's list so a
    # row that nobody has looked at since a punch created it is
    # distinguishable from one a manager typed. Set at the point of writing
    # by every path that creates or edits a record. Rows that predate the
    # field are labelled best-effort by migration 0008, whose docstring
    # states exactly what that label can and cannot mean.
    source = models.CharField(max_length=12, choices=Source.choices, default=Source.MANUAL)

    # Deviation from the planned shift, in minutes, after the branch's
    # grace period. Stored rather than derived on read so the manager's
    # "show me only the exceptions" filter is a plain indexed query over
    # a month rather than a per-row recomputation, and so the number a
    # manager reviewed is still the number recorded afterwards even if the
    # shift is later edited. Recomputed by
    # scheduling.attendance.apply_exception_minutes on every write.
    #
    # Deliberately minutes, not the booleans both reference projects use
    # (Frappe's late_entry/early_exit Checks, Horilla's
    # AttendanceLateComeEarlyOut rows, which carry no duration at all):
    # "3 minutes late" and "90 minutes late" are different conversations,
    # and a boolean cannot tell them apart.
    late_minutes = models.PositiveIntegerField(default=0)
    early_leave_minutes = models.PositiveIntegerField(default=0)

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


class AttendancePunch(models.Model):
    """One clock event — the raw evidence layer under ActualWorkRecord.

    Design note (see docs/ai-handoff/08_ATTENDANCE.md for the full
    comparison): both mature open-source references studied for this
    feature — Horilla (Django, LGPL-2.1) and Frappe HR (GPL-3.0) — split
    attendance into exactly two layers, a raw punch log and a per-day
    aggregate that payroll reads. This project already had the per-day
    aggregate (ActualWorkRecord, unique per employee+date, which is also
    what both references key their daily row on), so only this punch layer
    was missing. Neither project's code is used here: both are copyleft,
    so the *design* was taken and the implementation written from scratch.

    One immutable row per event, carrying its own `kind`, rather than
    Horilla's single row holding a clock_in/clock_out pair. A paired row
    turns "the employee forgot to clock out" into an UPDATE of an existing
    row (Horilla's own `duration()` even back-fills clock_out to `now` as a
    side effect of being read), which is the wrong shape for something
    payroll is derived from. Append-only rows can be audited, replayed and
    never silently rewritten: nothing in the API updates or deletes a
    punch, and a mistaken punch is answered by another punch plus a
    correction request, exactly like a till roll.

    A punch NEVER confirms attendance by itself. It feeds
    ActualWorkRecord via scheduling.attendance.rebuild_from_punches, which
    always leaves the day at status=PENDING for a manager to confirm — so
    the wage engine's existing contract (it only reads MANAGER_CONFIRMED /
    ADMIN_LOCKED records; see wages/calculation.py) is unchanged, and no
    employee can move their own pay by clocking in.
    """

    class Kind(models.TextChoices):
        CLOCK_IN = 'clock_in', 'Clock in'
        CLOCK_OUT = 'clock_out', 'Clock out'
        BREAK_START = 'break_start', 'Break start'
        BREAK_END = 'break_end', 'Break end'

    class Source(models.TextChoices):
        SELF = 'self', 'Employee self-service'
        MANAGER = 'manager', 'Entered by a manager on the employee\'s behalf'

    employee = models.ForeignKey('staff.StaffMember', on_delete=models.CASCADE, related_name='attendance_punches')
    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE, related_name='attendance_punches')
    # The *business* day this punch belongs to, which is not simply
    # punched_at's calendar date: a 01:30 clock-out from a shift that
    # started at 22:00 belongs to the previous business day. Resolved once,
    # at punch time, by scheduling.attendance.business_date_for() using the
    # branch's own cutover hour, and stored — so the day a punch counts
    # toward can't silently change later if that setting is retuned.
    # (Frappe HR infers an overnight shift from end_time < start_time on
    # its Shift Type; Horilla keeps clock_in_date separate from
    # attendance_date, which is the approach followed here.)
    work_date = models.DateField()
    kind = models.CharField(max_length=12, choices=Kind.choices)
    # Always server time (timezone.now()), never a client-supplied clock —
    # a phone with a wrong or deliberately-set clock must not be able to
    # move an attendance time.
    punched_at = models.DateTimeField()
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.SELF)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['work_date', 'employee_id', 'punched_at']
        indexes = [
            models.Index(fields=['branch', 'work_date'], name='punch_branch_date_idx'),
            models.Index(fields=['employee', 'work_date'], name='punch_employee_date_idx'),
        ]
        verbose_name_plural = 'attendance punches'

    def __str__(self):
        return f'{self.employee_id} {self.work_date} {self.kind} @{self.punched_at:%H:%M}'


class AttendanceCorrectionRequest(models.Model):
    """An employee's request to fix one day's attendance — the 補正申請 /
    补卡 flow (forgot to clock in, clocked out late, was actually absent).

    Modelled as its own record, following Frappe HR's separate
    `Attendance Request` doctype rather than Horilla's approach of smearing
    request state across the attendance row itself (`is_validate_request`,
    `is_validate_request_approved`, `request_type`, `requested_data` JSON).
    A separate record means a day can have a full history of who asked for
    what and who decided, instead of one in-flight request overwriting the
    last; it also keeps request state out of the row the wage engine reads.

    Approving one is the ONLY path by which an employee's own submission
    reaches ActualWorkRecord, and approval is a manager action — so the
    "employee can never move their own pay" rule holds here too.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Awaiting manager decision'
        APPROVED = 'approved', 'Approved and applied'
        REJECTED = 'rejected', 'Rejected'
        WITHDRAWN = 'withdrawn', 'Withdrawn by the employee'

    employee = models.ForeignKey('staff.StaffMember', on_delete=models.CASCADE, related_name='attendance_corrections')
    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE, related_name='attendance_corrections')
    work_date = models.DateField()

    # What the employee says the day actually was. All optional except the
    # reason: a request may be "I was absent" (requested_absent) with no
    # times at all, or purely a break correction.
    requested_start = models.TimeField(null=True, blank=True)
    requested_end = models.TimeField(null=True, blank=True)
    requested_break_minutes = models.PositiveIntegerField(null=True, blank=True)
    requested_crosses_midnight = models.BooleanField(default=False)
    requested_absent = models.BooleanField(default=False)
    # Never blank — an unexplained attendance change is exactly what this
    # whole flow exists to prevent.
    reason = models.TextField()

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['branch', 'status'], name='correction_branch_status_idx'),
            models.Index(fields=['employee', 'work_date'], name='correction_employee_date_idx'),
        ]
        # "At most one PENDING request per employee per day" is enforced in
        # AttendanceCorrectionRequestSerializer, not here: MySQL ignores the
        # condition on a conditional UniqueConstraint (Django raises
        # models.W036 for exactly this — see inventory.Product), so a
        # partial index here would be silently absent in production and
        # give a false sense of protection.

    def __str__(self):
        return f'{self.employee_id} {self.work_date} [{self.status}]'


class AttendanceChangeLog(models.Model):
    """Append-only record of every change to one day's ActualWorkRecord.

    The attendance row is a payroll input, so "who changed this day, when,
    from what, to what, and why" has to survive the change itself. Both
    reference projects have an equivalent (Horilla's HorillaAuditLog,
    Frappe's track_changes); this project has no generic audit framework,
    so attendance carries its own narrow one rather than acquiring a
    general-purpose dependency for a single model.

    `before`/`after` hold only the attendance-relevant fields, as plain
    JSON-safe values, so a log entry stays readable even after the record
    it describes has been deleted (hence on_delete=SET_NULL).
    """

    class Source(models.TextChoices):
        PUNCH = 'punch', 'Rebuilt from clock punches'
        MANUAL = 'manual', 'Edited directly by a manager'
        CORRECTION = 'correction', 'Applied from an approved correction request'
        GENERATED = 'generated', 'Generated from the published schedule'
        STATUS = 'status', 'Confirmation / lock state change'

    record = models.ForeignKey(
        ActualWorkRecord, on_delete=models.SET_NULL, null=True, blank=True, related_name='change_logs',
    )
    # Denormalized so a log entry still says who/when/where after its
    # record is gone.
    employee = models.ForeignKey('staff.StaffMember', on_delete=models.CASCADE, related_name='attendance_change_logs')
    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE, related_name='attendance_change_logs')
    work_date = models.DateField()

    source = models.CharField(max_length=12, choices=Source.choices)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    correction_request = models.ForeignKey(
        AttendanceCorrectionRequest, on_delete=models.SET_NULL, null=True, blank=True, related_name='change_logs',
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-changed_at']
        indexes = [
            models.Index(fields=['branch', 'work_date'], name='changelog_branch_date_idx'),
        ]

    def __str__(self):
        return f'{self.employee_id} {self.work_date} [{self.source}]'
