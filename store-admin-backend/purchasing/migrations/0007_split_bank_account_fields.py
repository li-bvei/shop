from django.db import migrations, models


def split_bank_account(apps, schema_editor):
    """Best-effort split of the old free-text bank_account field (format was
    always "<bank name><branch name><account number>" separated by
    whitespace, per the placeholder hint shown on the old form) into the new
    structured fields. Only one real supplier record ever had this field
    filled in at the time of this migration, so a simple whitespace split
    covers the actual data; anything that doesn't split into that shape is
    left as bank_name so no data is silently dropped.
    """
    Supplier = apps.get_model('purchasing', 'Supplier')
    for supplier in Supplier.objects.exclude(bank_account=''):
        parts = supplier.bank_account.split()
        if len(parts) >= 3:
            supplier.bank_name = parts[0]
            supplier.branch_name = parts[1]
            supplier.account_number = parts[-1]
        elif len(parts) == 2:
            supplier.bank_name, supplier.account_number = parts
        elif parts:
            supplier.bank_name = parts[0]
        supplier.save(update_fields=['bank_name', 'branch_name', 'account_number'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0006_supplier_bank_account_furigana'),
    ]

    operations = [
        migrations.RenameField(
            model_name='supplier',
            old_name='bank_account_furigana',
            new_name='account_holder_furigana',
        ),
        migrations.AddField(
            model_name='supplier',
            name='bank_name',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='supplier',
            name='bank_name_furigana',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='supplier',
            name='branch_name',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='supplier',
            name='branch_name_furigana',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='supplier',
            name='account_type',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='supplier',
            name='account_number',
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.RunPython(split_bank_account, noop),
        migrations.RemoveField(
            model_name='supplier',
            name='bank_account',
        ),
    ]
