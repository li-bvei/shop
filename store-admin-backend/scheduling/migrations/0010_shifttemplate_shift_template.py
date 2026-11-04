import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('branches', '0001_initial'),
        ('scheduling', '0009_backfill_attendance_exception_minutes'),
    ]

    operations = [
        migrations.CreateModel(
            name='ShiftTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(blank=True, max_length=40)),
                ('start_time', models.TimeField()),
                ('end_time', models.TimeField()),
                ('break_minutes', models.PositiveIntegerField(default=0)),
                ('color', models.CharField(choices=[('blue', 'Blue'), ('green', 'Green'), ('orange', 'Orange'), ('purple', 'Purple'), ('red', 'Red'), ('teal', 'Teal'), ('gray', 'Gray')], default='blue', max_length=10)),
                ('sort_order', models.PositiveSmallIntegerField(default=0)),
                ('active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='shift_templates', to='branches.branch')),
            ],
            options={
                'ordering': ['branch_id', 'sort_order', 'start_time', 'id'],
            },
        ),
        migrations.AddField(
            model_name='shift',
            name='template',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='shifts', to='scheduling.shifttemplate'),
        ),
    ]
