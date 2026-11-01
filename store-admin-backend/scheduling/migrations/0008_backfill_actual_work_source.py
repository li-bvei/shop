"""Backfill ActualWorkRecord.source for rows that predate the field.

0007 added `source` with default 'manual'. That is the safe default for a
new row, but it describes none of the history: before this field existed,
nothing recorded where a day's times came from.

What CAN be said about an existing row, and what cannot:

  * `shift_id IS NULL` — never scheduled (walk-in cover, a day typed in by
    hand). 'manual' is correct and the row is left alone.
  * `adjustment_reason` non-empty — a manager definitely touched this row.
    The serializer requires that field whenever the actual times differ
    from the shift (ActualWorkRecordSerializer.validate), and the unlock
    action appends to it; nothing else wrote it before this release. So a
    non-empty reason is a positive marker of a hand edit, not a guess, and
    the row stays 'manual'.
  * `shift_id IS NOT NULL` with an empty `adjustment_reason` — this day was
    scheduled and carries no sign of having been edited, so it is labelled
    'plan'.

That last one is a BEST-EFFORT LABEL, not a reconstruction. `shift_id`
survives a manager's edit untouched, so a day that a manager re-typed to
exactly the planned times, or edited before the reason field was enforced,
is indistinguishable from one generated straight from the schedule and will
read as 'plan'. The information needed to tell those apart was never
recorded, and this migration does not pretend otherwise. Rows written from
this release onwards are labelled at the point of writing
(generate_actual_records -> 'plan', perform_create/perform_update ->
'manual', punches -> 'punch', corrections -> 'correction'), so the
ambiguity is confined to data that predates the field.

Why label at all rather than leave everything 'manual': the manager's list
shows this column to answer "has anyone actually looked at this day?", and
on a month of scheduled history 'manual' everywhere is more misleading than
'plan' with a documented limit.

`source` is descriptive provenance only. wages/calculation.py does not read
it (it reads status, absent, actual_start, actual_end and
actual_break_minutes), and no attendance value or status is written here, so
this migration cannot change any wage result.

Reversible: the reverse puts those rows back to 'manual', which is the
value 0007's default gave them, so migrating backwards past 0007 leaves
exactly the state that existed before.
"""
from django.db import migrations


def set_plan_source(apps, schema_editor):
    ActualWorkRecord = apps.get_model('scheduling', 'ActualWorkRecord')
    ActualWorkRecord.objects.filter(
        shift__isnull=False, adjustment_reason='',
    ).update(source='plan')


def unset_plan_source(apps, schema_editor):
    ActualWorkRecord = apps.get_model('scheduling', 'ActualWorkRecord')
    ActualWorkRecord.objects.filter(source='plan').update(source='manual')


class Migration(migrations.Migration):

    dependencies = [
        ('scheduling', '0007_actualworkrecord_early_leave_minutes_and_more'),
    ]

    operations = [
        migrations.RunPython(set_plan_source, unset_plan_source),
    ]
