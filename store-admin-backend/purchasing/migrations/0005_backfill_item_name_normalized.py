from django.db import migrations

from purchasing.utils import normalize_item_name


def backfill(apps, schema_editor):
    PurchaseRecord = apps.get_model('purchasing', 'PurchaseRecord')
    records = list(PurchaseRecord.objects.only('id', 'item_name'))
    for record in records:
        record.item_name_normalized = normalize_item_name(record.item_name)
    PurchaseRecord.objects.bulk_update(records, ['item_name_normalized'], batch_size=500)


def noop_reverse(apps, schema_editor):
    # Nothing to reverse to — item_name_normalized is purely derived from
    # item_name, so clearing it back to '' loses no information.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0004_add_item_name_normalized'),
    ]

    operations = [
        migrations.RunPython(backfill, noop_reverse),
    ]
