from django.db import migrations


def backfill(apps, schema_editor):
    Branch = apps.get_model('branches', 'Branch')
    BranchScheduleSetting = apps.get_model('scheduling', 'BranchScheduleSetting')
    for branch in Branch.objects.all():
        BranchScheduleSetting.objects.get_or_create(branch=branch)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('scheduling', '0002_branchschedulesetting'),
        ('branches', '0003_alter_branch_organization_and_code'),
    ]

    operations = [
        migrations.RunPython(backfill, noop_reverse),
    ]
