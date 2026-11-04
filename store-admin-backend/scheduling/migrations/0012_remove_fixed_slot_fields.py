from django.db import migrations


class Migration(migrations.Migration):
    """Drop the three fixed slots now that 0011 has copied them into
    ShiftTemplate. Reversing re-adds the columns (at their old defaults)
    before 0011's reverse writes the template times back into them."""

    dependencies = [
        ('scheduling', '0011_shift_templates_from_fixed_slots'),
    ]

    operations = [
        migrations.RemoveField(model_name='branchschedulesetting', name='morning_start'),
        migrations.RemoveField(model_name='branchschedulesetting', name='morning_end'),
        migrations.RemoveField(model_name='branchschedulesetting', name='afternoon_start'),
        migrations.RemoveField(model_name='branchschedulesetting', name='afternoon_end'),
        migrations.RemoveField(model_name='branchschedulesetting', name='full_day_start'),
        migrations.RemoveField(model_name='branchschedulesetting', name='full_day_end'),
        migrations.RemoveField(model_name='branchschedulesetting', name='full_day_break_start'),
        migrations.RemoveField(model_name='branchschedulesetting', name='full_day_break_end'),
    ]
