from django.db import migrations, models

# The date the branch-wide "float default" feature shipped. Reports on/after
# it were displayed with the branch's float added on top of the counted
# quantities (computed at display time, never stored); reports before it
# never had the float applied.
FLOAT_FEATURE_CUTOFF = '2026-09-15'


def backfill_float(apps, schema_editor):
    """Freeze the float each existing report was *already being displayed
    with* into the report itself, so moving to a per-report float changes no
    saved day's totals. Reports before the cutoff keep an empty float (they
    never had one applied)."""
    DailyReport = apps.get_model('dailyreports', 'DailyReport')
    CashRegisterDefaults = apps.get_model('dailyreports', 'CashRegisterDefaults')
    defaults_by_branch = {
        d.branch_id: d.denomination_defaults or {} for d in CashRegisterDefaults.objects.all()
    }
    for report in DailyReport.objects.filter(date__gte=FLOAT_FEATURE_CUTOFF).iterator():
        float_counts = defaults_by_branch.get(report.branch_id)
        if float_counts:
            report.cash_register_float = float_counts
            report.save(update_fields=['cash_register_float'])


class Migration(migrations.Migration):

    dependencies = [
        ('dailyreports', '0003_cashregisterdefaults'),
    ]

    operations = [
        migrations.AddField(
            model_name='dailyreport',
            name='cash_register_float',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(backfill_float, migrations.RunPython.noop),
    ]
