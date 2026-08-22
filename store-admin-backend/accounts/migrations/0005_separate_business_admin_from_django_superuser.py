from django.db import migrations


def clear_django_superuser_flags(apps, schema_editor):
    """The business `admin` role and Django's own is_staff/is_superuser
    flags used to be conflated (every seeded admin account got both) —
    that's no longer safe now that Organizations exist, since Django's
    admin site has no Organization scoping at all and would let a
    business admin from any one Organization read/write every other
    Organization's data directly. Platform-level cross-tenant access must
    go through a real Django superuser account created separately
    (`createsuperuser`), never the business `admin` role."""
    User = apps.get_model('accounts', 'User')
    User.objects.filter(role='admin').update(is_staff=False, is_superuser=False)


def noop_reverse(apps, schema_editor):
    # Deliberately not reversible — restoring superuser access on business
    # accounts is a decision for a human, not an automatic migration
    # rollback.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_alter_user_organization'),
    ]

    operations = [
        migrations.RunPython(clear_django_superuser_flags, noop_reverse),
    ]
