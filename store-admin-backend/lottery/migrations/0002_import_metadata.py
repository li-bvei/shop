from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('lottery', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='dabingperson',
            name='contact',
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name='kyotorecord',
            name='quantity',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='kyotorecord',
            name='source_payload',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='kyotorecord',
            name='source_row',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='kyotorecord',
            name='source_sheet',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='dabingrecord',
            name='contact_snapshot',
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name='dabingrecord',
            name='source_payload',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='dabingrecord',
            name='source_row',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='dabingrecord',
            name='source_sheet',
            field=models.CharField(blank=True, max_length=100),
        ),
    ]
