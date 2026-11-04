"""Attendance derivation: clock punches -> one day's ActualWorkRecord.

The invariant this whole module exists to protect:

    A punch is EVIDENCE. A manager's confirmation is AUTHORITY.

Everything here writes ActualWorkRecord rows at status=PENDING and never
promotes one to MANAGER_CONFIRMED / ADMIN_LOCKED. The wage engine reads
only confirmed/locked records (wages/calculation.py), so no employee can
move their own pay by clocking in, and the payroll contract that existed
before self-service attendance is byte-for-byte the same one afterwards.

Three further rules follow from that and are enforced below rather than
left to call sites:

  * An ADMIN_LOCKED day is never rewritten. A locked day belongs to a
    closed wage month; a late punch must not silently reopen it. Such a
    punch is still stored (it is evidence), it just does not rewrite the
    record — the manager unlocks deliberately if the day really must
    change.
  * A day a manager has already confirmed is not silently re-derived
    either, for the same reason: a later punch would otherwise overwrite a
    human decision. Punches after confirmation are recorded and surfaced,
    not applied. A day that is only confirmed because it was generated from
    the published schedule (source=PLAN) is NOT such a decision — nobody
    has looked at it — so the employee's real punches replace it and put it
    back to PENDING. Otherwise attendance on every scheduled day would be
    the plan's times forever, whatever the employee actually clocked.
  * Every write of an attendance record pairs it with log_change(), which
    appends an AttendanceChangeLog entry inside the same transaction — here
    for punches and corrections, and in scheduling/views.py for manager
    edits, deletions, confirmations, locks and schedule generation. There is
    no path that changes an attendance record without leaving a trail.
"""
from datetime import date, datetime, time, timedelta

from django.db import transaction
from django.utils import timezone

from .models import (
    ActualWorkRecord, AttendanceChangeLog, AttendancePunch, BranchScheduleSetting, Shift,
)

# How far past midnight a punch can fall and still belong to the previous
# business day, when a branch has no schedule setting row at all. Matches
# BranchScheduleSetting.attendance_day_cutover_hour's own default.
DEFAULT_DAY_CUTOVER_HOUR = 5

# Fields of ActualWorkRecord that the change log snapshots. Only the ones
# that describe the day's attendance — not timestamps or FK bookkeeping,
# which would make every diff noisy without saying anything.
LOGGED_FIELDS = (
    'actual_start', 'actual_end', 'crosses_midnight', 'actual_break_minutes',
    'absent', 'statutory_holiday', 'status', 'source', 'late_minutes',
    'early_leave_minutes', 'adjustment_reason',
)


def setting_for(branch):
    """The branch's attendance policy, or None. Callers must cope with
    None: a branch created before BranchScheduleSetting existed, or one
    whose row was deleted, still has to be able to record attendance."""
    return BranchScheduleSetting.objects.filter(branch=branch).first()


def _cutover_hour(setting):
    return setting.attendance_day_cutover_hour if setting else DEFAULT_DAY_CUTOVER_HOUR


def business_date_for(branch, moment, setting=None):
    """The business day `moment` belongs to at `branch`.

    A punch before the branch's cutover hour belongs to the PREVIOUS
    calendar day — so clocking out at 01:30 from a shift that began at
    22:00 lands on the day the shift started, not on the next one. Without
    this, every overnight shift would be split across two attendance rows,
    each half a shift long, and at a month boundary half of it would fall
    into the wrong wage month.

    `moment` is interpreted in the project's active timezone (Asia/Tokyo in
    this deployment), never in UTC: a 00:30 JST punch is the previous
    business day in Osaka regardless of what the UTC date happens to be.
    """
    if setting is None:
        setting = setting_for(branch)
    local = timezone.localtime(moment) if timezone.is_aware(moment) else moment
    if local.hour < _cutover_hour(setting):
        return (local - timedelta(days=1)).date()
    return local.date()


def _minutes_between(earlier, later):
    return max(0, int((later - earlier).total_seconds() // 60))


def _combine(work_date, t, crosses_midnight=False):
    """A date+time as a naive datetime, with `crosses_midnight` pushing the
    time onto the following day — the same convention the rest of
    scheduling uses (see services._minute_range)."""
    day = work_date + timedelta(days=1) if crosses_midnight else work_date
    return datetime.combine(day, t)


def summarize_punches(punches):
    """Reduce one day's punches to (start, end, break_minutes,
    crosses_midnight, problems).

    `punches` must be that day's punches in `punched_at` order.

    Start is the first clock-in and end the last clock-out — the
    "first check-in / last check-out" rule both reference projects default
    to (Frappe's Shift Type literally names it
    `working_hours_calculation_based_on = "First Check-in and Last
    Check-out"`), because a mid-shift pair of punches is nearly always
    somebody stepping out, not a second shift.

    Break minutes are the sum of completed break_start -> break_end pairs.
    This project tracks breaks explicitly rather than inferring them from
    gaps between punches: the wage engine already deducts
    `actual_break_minutes`, and the branch shift template already defines a
    named break window, so an inferred gap would contradict data the system
    already holds. (Horilla has no break concept at all; Frappe infers
    from alternating punches.)

    `problems` names what is incomplete, for the manager's review list —
    it never silently guesses a missing value.
    """
    start_at = None
    end_at = None
    break_minutes = 0
    open_break_at = None
    problems = []

    for punch in punches:
        at = timezone.localtime(punch.punched_at) if timezone.is_aware(punch.punched_at) else punch.punched_at
        if punch.kind == AttendancePunch.Kind.CLOCK_IN:
            if start_at is None:
                start_at = at
        elif punch.kind == AttendancePunch.Kind.CLOCK_OUT:
            end_at = at
        elif punch.kind == AttendancePunch.Kind.BREAK_START:
            # A second break_start without an intervening break_end means a
            # missed punch; keep the earliest so the break isn't undercounted,
            # and flag it rather than quietly picking one.
            if open_break_at is None:
                open_break_at = at
            else:
                problems.append('break-not-closed')
        elif punch.kind == AttendancePunch.Kind.BREAK_END:
            if open_break_at is None:
                problems.append('break-end-without-start')
            else:
                break_minutes += _minutes_between(open_break_at, at)
                open_break_at = None

    if open_break_at is not None:
        # An unclosed break is NOT counted — guessing its length would be
        # inventing a number that directly reduces paid time.
        problems.append('break-not-closed')
    if start_at is None:
        problems.append('missing-clock-in')
    if end_at is None:
        problems.append('missing-clock-out')
    if start_at and end_at and end_at <= start_at:
        problems.append('clock-out-before-clock-in')

    crosses_midnight = bool(start_at and end_at and end_at.date() > start_at.date())
    return (
        start_at.time().replace(second=0, microsecond=0) if start_at else None,
        end_at.time().replace(second=0, microsecond=0) if end_at else None,
        break_minutes,
        crosses_midnight,
        problems,
    )


def shift_for(employee, work_date):
    """The planned shift this day's attendance is measured against, if any.
    A day with no shift simply has no late/early deviation to compute —
    unscheduled cover is not "late"."""
    return Shift.objects.filter(employee=employee, work_date=work_date).order_by('planned_start').first()


def exception_minutes(record, shift, setting):
    """(late_minutes, early_leave_minutes) for `record` against `shift`.

    Both are measured past the branch's grace period and clamped at zero,
    so arriving early or leaving late is never recorded as a negative
    lateness. A record with no shift, no times, or marked absent has no
    deviation to report: absence is its own state, not an extreme lateness.
    """
    if shift is None or record.absent or not record.actual_start or not record.actual_end:
        return 0, 0

    late_grace = setting.late_grace_minutes if setting else 0
    early_grace = setting.early_leave_grace_minutes if setting else 0

    planned_start = _combine(record.work_date, shift.planned_start)
    planned_end = _combine(record.work_date, shift.planned_end, shift.crosses_midnight)
    actual_start = _combine(record.work_date, record.actual_start)
    actual_end = _combine(record.work_date, record.actual_end, record.crosses_midnight)

    late = max(0, _minutes_between(planned_start, actual_start) - late_grace)
    early = max(0, _minutes_between(actual_end, planned_end) - early_grace)
    return late, early


def apply_exception_minutes(record, setting=None):
    """Recompute and set (but do not save) `record`'s deviation minutes."""
    if setting is None:
        setting = setting_for(record.branch)
    record.late_minutes, record.early_leave_minutes = exception_minutes(
        record, shift_for(record.employee, record.work_date), setting,
    )
    return record


def snapshot_for_log(record):
    """The attendance-relevant fields of `record` as JSON-safe values, or
    None for an unsaved/absent record. Callers take this BEFORE mutating
    the instance — a snapshot read afterwards describes the new state, not
    the old one, and the log entry would record no change."""
    if record is None or record.pk is None:
        return None
    out = {}
    for field in LOGGED_FIELDS:
        value = getattr(record, field)
        out[field] = value.isoformat() if isinstance(value, (time, date, datetime)) else value
    return out


def log_change(record, *, source, before, actor, reason='', correction_request=None,
                employee=None, branch=None, work_date=None):
    """Write one append-only AttendanceChangeLog entry.

    `employee`/`branch`/`work_date` are only needed when `record` is None
    (a record being deleted), since the log has to outlive the row.
    """
    AttendanceChangeLog.objects.create(
        record=record,
        employee=employee or record.employee,
        branch=branch or record.branch,
        work_date=work_date or record.work_date,
        source=source,
        before=before,
        after=snapshot_for_log(record),
        reason=reason[:255],
        correction_request=correction_request,
        changed_by=actor if (actor is not None and getattr(actor, 'is_authenticated', False)) else None,
    )


def is_frozen(record):
    """True when a record must not be re-derived automatically.

    An admin has locked this day, or a manager has confirmed it; in both
    cases a later automatic rewrite would overwrite a human decision — and,
    for a locked day, a wage month that may already be closed. The punch
    itself is still stored; it just doesn't apply.

    A record still exactly as generate_actual_records wrote it
    (source=PLAN) is confirmed only by having been scheduled. That is the
    plan, not a manager's verdict on what happened, so it is not frozen:
    the day's punches are the better evidence and replace it.
    """
    if record is None:
        return False
    if record.status == ActualWorkRecord.Status.ADMIN_LOCKED:
        return True
    untouched_plan = record.source == ActualWorkRecord.Source.PLAN and not record.adjustment_reason
    return record.status == ActualWorkRecord.Status.MANAGER_CONFIRMED and not untouched_plan


def _plan_times(shift):
    return {
        'actual_start': shift.planned_start, 'actual_end': shift.planned_end,
        'crosses_midnight': shift.crosses_midnight, 'actual_break_minutes': shift.planned_break_minutes,
    }


def _plan_record(shift):
    """The day's record if it is still the untouched copy of `shift`.

    A non-empty adjustment_reason disqualifies it too: the serializer
    demands one whenever a person moves a day off its plan, so it is a
    positive sign of a hand edit — the same rule migration 0008 used to
    label history.
    """
    record = ActualWorkRecord.objects.filter(
        employee_id=shift.employee_id, work_date=shift.work_date, shift_id=shift.id,
    ).first()
    if (record is None or record.source != ActualWorkRecord.Source.PLAN or record.adjustment_reason
            or record.status == ActualWorkRecord.Status.ADMIN_LOCKED):
        return None
    return record


@transaction.atomic
def sync_plan_record(shift, actor):
    """Bring a generated record back in line with its shift after the shift
    was retimed. Returns True if the record changed.

    Only a record that is still the plan's own copy is touched. Once a
    punch, a correction or a manager has written the day, its times are
    what happened and a later schedule edit must not overwrite them; a
    locked day is never touched at all. Without this, moving a shift from
    10:00-15:00 to 12:00-18:00 after the record was generated would leave
    the day confirmed — and paid — at the old times.
    """
    record = _plan_record(shift)
    if record is None:
        return False
    times = _plan_times(shift)
    if all(getattr(record, field) == value for field, value in times.items()):
        return False
    before = snapshot_for_log(record)
    for field, value in times.items():
        setattr(record, field, value)
    apply_exception_minutes(record)
    record.updated_by = actor if (actor is not None and getattr(actor, 'is_authenticated', False)) else None
    record.save()
    log_change(record, source=AttendanceChangeLog.Source.GENERATED, before=before, actor=actor,
               reason='shift_retimed')
    return True


@transaction.atomic
def discard_plan_record(shift, actor):
    """Remove the generated record of a shift that is being deleted.

    A generated record is pre-confirmed, so leaving it behind would keep
    paying a day that is no longer scheduled. Records a punch, correction or
    manager has written are kept (the day may really have been worked) and
    simply lose their shift link, as before; locked days are never touched.
    """
    record = _plan_record(shift)
    if record is None:
        return False
    before = snapshot_for_log(record)
    employee, branch, work_date = record.employee, record.branch, record.work_date
    record.delete()
    log_change(None, source=AttendanceChangeLog.Source.GENERATED, before=before, actor=actor,
               reason='shift_deleted', employee=employee, branch=branch, work_date=work_date)
    return True


@transaction.atomic
def rebuild_from_punches(employee, branch, work_date, actor=None):
    """Re-derive one day's ActualWorkRecord from that day's punches.

    Returns (record, applied, problems). `applied` is False when the day
    was frozen (see is_frozen) or had no punches at all — the caller
    surfaces that rather than the record silently not changing.

    The derived record is always left at status=PENDING: deriving
    attendance is not confirming it.
    """
    punches = list(
        AttendancePunch.objects.filter(employee=employee, work_date=work_date).order_by('punched_at')
    )
    record = ActualWorkRecord.objects.filter(employee=employee, work_date=work_date).first()

    if not punches:
        return record, False, ['no-punches']
    if is_frozen(record):
        return record, False, ['record-already-confirmed']

    start, end, break_minutes, crosses_midnight, problems = summarize_punches(punches)
    setting = setting_for(branch)
    before = snapshot_for_log(record)

    if record is None:
        record = ActualWorkRecord(employee=employee, branch=branch, work_date=work_date)
    record.shift = record.shift or shift_for(employee, work_date)
    record.actual_start = start
    record.actual_end = end
    record.crosses_midnight = crosses_midnight
    record.actual_break_minutes = break_minutes
    record.absent = False
    record.source = ActualWorkRecord.Source.PUNCH
    record.status = ActualWorkRecord.Status.PENDING
    record.updated_by = actor if (actor is not None and getattr(actor, 'is_authenticated', False)) else None
    apply_exception_minutes(record, setting)
    record.save()

    log_change(record, source=AttendanceChangeLog.Source.PUNCH, before=before, actor=actor,
               reason=','.join(problems))
    return record, True, problems


@transaction.atomic
def apply_correction(correction, actor):
    """Apply an APPROVED correction request to its day's record.

    Writes the record at status=PENDING, exactly like a punch-derived one:
    an approved correction states what the day WAS, and a manager still
    confirms it into payroll. A locked day is refused outright — the admin
    unlocks first, deliberately.
    """
    record = ActualWorkRecord.objects.filter(
        employee=correction.employee, work_date=correction.work_date,
    ).first()
    if record is not None and record.status == ActualWorkRecord.Status.ADMIN_LOCKED:
        return record, False

    before = snapshot_for_log(record)
    if record is None:
        record = ActualWorkRecord(
            employee=correction.employee, branch=correction.branch, work_date=correction.work_date,
        )
    record.shift = record.shift or shift_for(correction.employee, correction.work_date)
    record.absent = correction.requested_absent
    if correction.requested_absent:
        # An absent day keeps no worked times: leaving stale times behind
        # would let a day read as both absent and worked.
        record.actual_start = None
        record.actual_end = None
        record.actual_break_minutes = 0
        record.crosses_midnight = False
    else:
        if correction.requested_start is not None:
            record.actual_start = correction.requested_start
        if correction.requested_end is not None:
            record.actual_end = correction.requested_end
        if correction.requested_break_minutes is not None:
            record.actual_break_minutes = correction.requested_break_minutes
        record.crosses_midnight = correction.requested_crosses_midnight
    record.source = ActualWorkRecord.Source.CORRECTION
    record.status = ActualWorkRecord.Status.PENDING
    record.adjustment_reason = correction.reason[:255]
    record.updated_by = actor if (actor is not None and getattr(actor, 'is_authenticated', False)) else None
    apply_exception_minutes(record)
    record.save()

    log_change(record, source=AttendanceChangeLog.Source.CORRECTION, before=before, actor=actor,
               reason=correction.reason, correction_request=correction)
    return record, True


def open_state(employee, work_date):
    """What the employee's own screen needs to show: which button is next.

    Returned as plain flags rather than a single "state" string so the UI
    can disable rather than hide an action (a hidden button reads as a
    broken page), and so a day that is already closed still shows its
    totals.
    """
    punches = list(
        AttendancePunch.objects.filter(employee=employee, work_date=work_date).order_by('punched_at')
    )
    kinds = [p.kind for p in punches]
    clocked_in = AttendancePunch.Kind.CLOCK_IN in kinds
    clocked_out = AttendancePunch.Kind.CLOCK_OUT in kinds
    on_break = False
    for kind in kinds:
        if kind == AttendancePunch.Kind.BREAK_START:
            on_break = True
        elif kind == AttendancePunch.Kind.BREAK_END:
            on_break = False
    return {
        'workDate': work_date.isoformat(),
        'clockedIn': clocked_in,
        'clockedOut': clocked_out,
        'onBreak': on_break,
        'canClockIn': not clocked_in,
        'canClockOut': clocked_in and not clocked_out and not on_break,
        'canStartBreak': clocked_in and not clocked_out and not on_break,
        'canEndBreak': on_break,
        'punchCount': len(punches),
    }


def next_punch_error(employee, work_date, kind):
    """The reason `kind` is not a legal next punch, or None.

    Ordering is enforced server-side, not merely by which button the UI
    offers: a replayed or hand-crafted request must not be able to write a
    clock-out with no clock-in, or two clock-ins, and leave the day's
    derived times nonsense.
    """
    state = open_state(employee, work_date)
    allowed = {
        AttendancePunch.Kind.CLOCK_IN: state['canClockIn'],
        AttendancePunch.Kind.CLOCK_OUT: state['canClockOut'],
        AttendancePunch.Kind.BREAK_START: state['canStartBreak'],
        AttendancePunch.Kind.BREAK_END: state['canEndBreak'],
    }
    if allowed.get(kind):
        return None
    return f'punch-not-allowed-{kind.replace("_", "-")}'
