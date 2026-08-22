from django.db import migrations


DEFAULT_ORG_CODE = 'default-store-group'
DEFAULT_ORG_NAME_ZH = '现有店铺集团'
DEFAULT_ORG_NAME_JA = '既存店舗グループ'


def backfill(apps, schema_editor):
    Organization = apps.get_model('organizations', 'Organization')
    Branch = apps.get_model('branches', 'Branch')
    User = apps.get_model('accounts', 'User')
    Supplier = apps.get_model('purchasing', 'Supplier')

    org, _ = Organization.objects.get_or_create(
        code=DEFAULT_ORG_CODE,
        defaults={'name_zh': DEFAULT_ORG_NAME_ZH, 'name_ja': DEFAULT_ORG_NAME_JA},
    )

    Branch.objects.filter(organization__isnull=True).update(organization=org)
    for branch in Branch.objects.filter(code__isnull=True):
        branch.code = branch.id
        branch.save(update_fields=['code'])

    User.objects.filter(organization__isnull=True).update(organization=org)
    Supplier.objects.filter(organization__isnull=True).update(organization=org)


def unbackfill(apps, schema_editor):
    # Irreversible in spirit (we don't want to silently null out real
    # tenant assignments on a rollback) — no-op keeps `migrate <app> zero`
    # from hard-failing, but this migration is not meant to be reversed
    # on a database with real data in it.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0001_initial'),
        ('branches', '0002_branch_code_branch_organization_and_more'),
        ('accounts', '0003_user_organization'),
        ('purchasing', '0002_supplier_organization'),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
