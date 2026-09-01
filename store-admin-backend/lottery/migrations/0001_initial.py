import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('organizations', '0002_backfill_default_organization'),
    ]

    operations = [
        migrations.CreateModel(
            name='DabingPerson',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('phone', models.CharField(blank=True, max_length=30)),
                ('birthday', models.DateField(blank=True, null=True)),
                ('mobile_model', models.CharField(blank=True, max_length=100)),
                ('note', models.TextField(blank=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='dabing_people', to='organizations.organization')),
            ],
            options={'ordering': ['name', 'id']},
        ),
        migrations.CreateModel(
            name='DabingStore',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('is_active', models.BooleanField(default=True)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='dabing_stores', to='organizations.organization')),
            ],
            options={'ordering': ['sort_order', 'id']},
        ),
        migrations.CreateModel(
            name='KyotoDrawBatch',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('draw_start_date', models.DateField()),
                ('draw_end_date', models.DateField()),
                ('publish_date', models.DateField()),
                ('label', models.CharField(blank=True, max_length=100)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='kyoto_draw_batches', to='organizations.organization')),
            ],
            options={'ordering': ['-draw_start_date', '-id']},
        ),
        migrations.CreateModel(
            name='KyotoPerson',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('phone', models.CharField(blank=True, max_length=30)),
                ('note', models.TextField(blank=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='kyoto_people', to='organizations.organization')),
            ],
            options={'ordering': ['name', 'id']},
        ),
        migrations.CreateModel(
            name='DabingRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('draw_date', models.DateField()),
                ('draw_time', models.CharField(blank=True, max_length=30)),
                ('phone_snapshot', models.CharField(blank=True, max_length=30)),
                ('mobile_model_snapshot', models.CharField(blank=True, max_length=100)),
                ('birthday_snapshot', models.DateField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_dabing_records', to=settings.AUTH_USER_MODEL)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='dabing_records', to='organizations.organization')),
                ('person', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='records', to='lottery.dabingperson')),
                ('store', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='records', to='lottery.dabingstore')),
            ],
            options={'ordering': ['-draw_date', 'store__sort_order', 'draw_time', 'id']},
        ),
        migrations.CreateModel(
            name='KyotoRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('phone_snapshot', models.CharField(blank=True, max_length=30)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('batch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='records', to='lottery.kyotodrawbatch')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_kyoto_records', to=settings.AUTH_USER_MODEL)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='kyoto_records', to='organizations.organization')),
                ('person', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='records', to='lottery.kyotoperson')),
            ],
            options={'ordering': ['-batch__publish_date', 'person__name', 'id']},
        ),
        migrations.AddConstraint(
            model_name='dabingstore',
            constraint=models.UniqueConstraint(fields=('organization', 'name'), name='unique_dabing_store_per_organization'),
        ),
        migrations.AddIndex(model_name='dabingperson', index=models.Index(fields=['organization', 'name'], name='lottery_dab_organiz_6bbef2_idx')),
        migrations.AddIndex(model_name='dabingperson', index=models.Index(fields=['organization', 'phone'], name='lottery_dab_organiz_7c2f5a_idx')),
        migrations.AddIndex(model_name='kyotodrawbatch', index=models.Index(fields=['organization', 'publish_date'], name='lottery_kyo_organiz_17d449_idx')),
        migrations.AddIndex(model_name='kyotodrawbatch', index=models.Index(fields=['organization', 'draw_start_date'], name='lottery_kyo_organiz_3d1d13_idx')),
        migrations.AddIndex(model_name='kyotoperson', index=models.Index(fields=['organization', 'name'], name='lottery_kyo_organiz_4c74c7_idx')),
        migrations.AddIndex(model_name='kyotoperson', index=models.Index(fields=['organization', 'phone'], name='lottery_kyo_organiz_5f5acd_idx')),
        migrations.AddIndex(model_name='dabingrecord', index=models.Index(fields=['organization', 'draw_date'], name='lottery_dab_organiz_1afcde_idx')),
        migrations.AddIndex(model_name='dabingrecord', index=models.Index(fields=['organization', 'store', 'draw_date'], name='lottery_dab_organiz_21f2e9_idx')),
        migrations.AddIndex(model_name='kyotorecord', index=models.Index(fields=['organization', 'batch'], name='lottery_kyo_organiz_7a1db4_idx')),
    ]
