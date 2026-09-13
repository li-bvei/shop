from django.db import transaction

from accounts.models import User
from branches.models import Branch
from paymentmethods.models import seed_default_payment_methods
from scheduling.services import seed_default_schedule_setting

from .models import Organization


class ProvisionError(Exception):
    """Raised for any validation failure — carries a stable machine-readable
    code (matching what the CLI command has always raised as CommandError
    messages) so both the management command and the platform API endpoint
    can present the same errors."""


def provision_organization(
    *, code, name_zh, name_ja,
    admin_account=None, admin_password=None,
    branch_code=None, branch_name_zh=None, branch_name_ja=None,
):
    """Atomically creates an Organization plus, optionally, its first branch
    and first business admin — the one place this logic lives, shared by
    `manage.py provision_organization` and the platform super admin's
    "new tenant" UI action.

    Branch and admin are each all-or-nothing groups: pass every field in a
    group or none of them.
    """
    if Organization.objects.filter(code=code).exists():
        raise ProvisionError('organization-code-already-exists')

    branch_args = (branch_code, branch_name_zh, branch_name_ja)
    if any(branch_args) and not all(branch_args):
        raise ProvisionError('branch-fields-incomplete')

    admin_args = (admin_account, admin_password)
    if any(admin_args) and not all(admin_args):
        raise ProvisionError('admin-fields-incomplete')

    if admin_account and User.objects.filter(username=admin_account).exists():
        raise ProvisionError('admin-account-already-exists')

    with transaction.atomic():
        organization = Organization.objects.create(code=code, name_zh=name_zh, name_ja=name_ja)

        branch = None
        if branch_code:
            # Branch.id is historically global. Prefixing with the tenant
            # code prevents collisions while `code` stays tenant-local.
            branch = Branch.objects.create(
                id=f'{organization.code}-{branch_code}',
                organization=organization, code=branch_code,
                name_zh=branch_name_zh, name_ja=branch_name_ja,
            )
            seed_default_payment_methods(branch)
            seed_default_schedule_setting(branch)

        admin = None
        if admin_account:
            admin = User(
                username=admin_account, first_name=admin_account,
                role=User.Role.ADMIN, organization=organization, branch=None,
                is_staff=False, is_superuser=False,
            )
            admin.set_password(admin_password)
            admin.save()

    return organization, branch, admin


def create_branch_for_organization(organization, *, code, name_zh, name_ja):
    """Same seeding a chain's own admin gets from BranchViewSet.perform_create
    — the platform super admin reaches the same path when helping a tenant
    that can't (or shouldn't have to) do it themselves."""
    branch = Branch.objects.create(
        id=f'{organization.code}-{code}', organization=organization,
        code=code, name_zh=name_zh, name_ja=name_ja,
    )
    seed_default_payment_methods(branch)
    seed_default_schedule_setting(branch)
    return branch
