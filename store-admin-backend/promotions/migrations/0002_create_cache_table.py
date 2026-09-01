from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    """Create the DB cache table configured in settings.CACHES so a fresh
    `migrate` is all a deploy needs — no separate `createcachetable` step.
    With no table name argument, createcachetable reads settings.CACHES;
    it is idempotent (skips a table that already exists)."""
    call_command('createcachetable', database=schema_editor.connection.alias, verbosity=0)


def drop_cache_table(apps, schema_editor):
    schema_editor.execute('DROP TABLE IF EXISTS promotions_cache_table')


class Migration(migrations.Migration):
    dependencies = [
        ('promotions', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_cache_table, drop_cache_table),
    ]
