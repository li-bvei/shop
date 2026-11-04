"""Turn each branch's three fixed schedule slots into ordinary templates.

Until this release BranchScheduleSetting held exactly three shift times —
morning, afternoon and full day — and the schedule grid could place only
those. This migration copies each branch's three into ShiftTemplate rows so
that nothing a branch had configured is lost, then 0012 drops the columns.

What it does, per branch:

  * creates three templates with the branch's own times, in the old order,
    with NO name. An unnamed template is displayed by its times
    ("10:30-15:00"), which describes it exactly; the branch can rename,
    retime or delete them like any template it creates itself.
  * the full-day break becomes `break_minutes` (break_end - break_start).
    Only the length matters to attendance and wages — both already read
    `planned_break_minutes` as a number of minutes — so the window's
    position is not kept.
  * links each existing Shift whose planned start and end equal one of the
    three to that template. That is the same rule the old grid used to
    decide which slot a shift was showing as; shifts that matched none of
    them (it called them "custom") stay unlinked. The link is only a label
    and colour: no shift's times change, so no attendance record and no
    wage result changes.

Reverse writes the first three templates' times back into the restored
columns (0012's reverse re-adds them first) and deletes all templates. The
full-day break window is not recoverable from a length alone, so the
reverse leaves it at the column default; that is the one thing a rollback
does not restore exactly.

Historical models only: the logic is deliberately self-contained so it
keeps behaving as it did when written.
"""
from datetime import date, datetime

from django.db import migrations

COLORS = ['blue', 'orange', 'green']


def _minutes(start, end):
    delta = datetime.combine(date.min, end) - datetime.combine(date.min, start)
    return max(0, int(delta.total_seconds() // 60))


def templates_from_slots(apps, schema_editor):
    BranchScheduleSetting = apps.get_model('scheduling', 'BranchScheduleSetting')
    ShiftTemplate = apps.get_model('scheduling', 'ShiftTemplate')
    Shift = apps.get_model('scheduling', 'Shift')

    for setting in BranchScheduleSetting.objects.all():
        slots = [
            (setting.morning_start, setting.morning_end, 0),
            (setting.afternoon_start, setting.afternoon_end, 0),
            (setting.full_day_start, setting.full_day_end,
             _minutes(setting.full_day_break_start, setting.full_day_break_end)),
        ]
        for index, (start, end, break_minutes) in enumerate(slots):
            template = ShiftTemplate.objects.create(
                branch_id=setting.branch_id, name='', start_time=start, end_time=end,
                break_minutes=break_minutes, color=COLORS[index], sort_order=index + 1,
            )
            Shift.objects.filter(
                branch_id=setting.branch_id, planned_start=start, planned_end=end, template__isnull=True,
            ).update(template=template)


def slots_from_templates(apps, schema_editor):
    BranchScheduleSetting = apps.get_model('scheduling', 'BranchScheduleSetting')
    ShiftTemplate = apps.get_model('scheduling', 'ShiftTemplate')

    for setting in BranchScheduleSetting.objects.all():
        first_three = list(
            ShiftTemplate.objects.filter(branch_id=setting.branch_id).order_by('sort_order', 'id')[:3]
        )
        if len(first_three) == 3:
            morning, afternoon, full_day = first_three
            setting.morning_start, setting.morning_end = morning.start_time, morning.end_time
            setting.afternoon_start, setting.afternoon_end = afternoon.start_time, afternoon.end_time
            setting.full_day_start, setting.full_day_end = full_day.start_time, full_day.end_time
            setting.save()
    ShiftTemplate.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('scheduling', '0010_shifttemplate_shift_template'),
    ]

    operations = [
        migrations.RunPython(templates_from_slots, slots_from_templates),
    ]
