"""Backfill ActualWorkRecord.late_minutes / early_leave_minutes.

0007 added both fields with default 0, which is right for a brand-new row
but wrong for the history already on disk: every record that predates the
fields reads as "arrived on time, left on time", so a manager opening the
attendance list with the default "only show exceptions" filter sees none of
the past months' real late arrivals or early departures. The filter is only
as good as these two columns (ActualWorkRecordFilter.filter_exception
queries them directly), so leaving them at 0 does not merely lose detail —
it makes the feature report the wrong answer about existing data.

The numbers are recomputed here from data that is already stored, using the
same rule as scheduling.attendance.exception_minutes:

    late  = (actual_start - planned_start) - branch late grace,   clamped >= 0
    early = (planned_end  - actual_end)    - branch early grace,  clamped >= 0

with `crosses_midnight` (on the shift for the planned end, on the record for
the actual end) pushing that time onto the following day, exactly as
scheduling uses it elsewhere. Rows with no shift, no times, or marked absent
have no deviation to measure and are left at 0 — an absence is its own
state, not an extreme lateness.

The logic is duplicated here rather than imported: a migration must keep
behaving the way it did when it ran, and importing the runtime module would
silently re-date this backfill to whatever that module says years from now.
Only historical models are used (apps.get_model), never runtime ones.

Cannot affect wages. wages/calculation.py reads status, absent,
actual_start, actual_end and actual_break_minutes — never these two fields
(nor `source`). No attendance time, status or absence flag is written here.

Reversible: the reverse sets both columns back to 0, which is exactly the
state 0007's defaults produced.
"""
from datetime import datetime, timedelta

from django.db import migrations

BATCH = 500


def _combine(work_date, value, next_day=False):
    day = work_date + timedelta(days=1) if next_day else work_date
    return datetime.combine(day, value)


def _minutes_between(earlier, later):
    return max(0, int((later - earlier).total_seconds() // 60))


def fill_exception_minutes(apps, schema_editor):
    ActualWorkRecord = apps.get_model('scheduling', 'ActualWorkRecord')
    BranchScheduleSetting = apps.get_model('scheduling', 'BranchScheduleSetting')

    grace = {
        s.branch_id: (s.late_grace_minutes, s.early_leave_grace_minutes)
        for s in BranchScheduleSetting.objects.all()
    }

    records = (
        ActualWorkRecord.objects
        .filter(
            shift__isnull=False, absent=False,
            actual_start__isnull=False, actual_end__isnull=False,
        )
        .select_related('shift')
        .iterator(chunk_size=BATCH)
    )

    pending = []
    for record in records:
        shift = record.shift
        late_grace, early_grace = grace.get(record.branch_id, (0, 0))

        planned_start = _combine(record.work_date, shift.planned_start)
        planned_end = _combine(record.work_date, shift.planned_end, shift.crosses_midnight)
        actual_start = _combine(record.work_date, record.actual_start)
        actual_end = _combine(record.work_date, record.actual_end, record.crosses_midnight)

        late = max(0, _minutes_between(planned_start, actual_start) - late_grace)
        early = max(0, _minutes_between(actual_end, planned_end) - early_grace)
        if (late, early) == (record.late_minutes, record.early_leave_minutes):
            continue

        record.late_minutes = late
        record.early_leave_minutes = early
        pending.append(record)
        if len(pending) >= BATCH:
            ActualWorkRecord.objects.bulk_update(pending, ['late_minutes', 'early_leave_minutes'])
            pending = []

    if pending:
        ActualWorkRecord.objects.bulk_update(pending, ['late_minutes', 'early_leave_minutes'])


def clear_exception_minutes(apps, schema_editor):
    ActualWorkRecord = apps.get_model('scheduling', 'ActualWorkRecord')
    ActualWorkRecord.objects.exclude(late_minutes=0, early_leave_minutes=0).update(
        late_minutes=0, early_leave_minutes=0,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('scheduling', '0008_backfill_actual_work_source'),
    ]

    operations = [
        migrations.RunPython(fill_exception_minutes, clear_exception_minutes),
    ]
