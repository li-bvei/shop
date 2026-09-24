import secrets

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q

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


def _generate_code(prefix, is_taken):
    """An opaque, slug-safe identifier. Codes are internal ids (they end up
    in Branch.id, API filters, URLs); what people read is the name, so nobody
    has to invent or remember one."""
    while True:
        code = f'{prefix}-{secrets.token_hex(4)}'
        if not is_taken(code):
            return code


def _next_branch_code(organization):
    """b1, b2, … — the first code no branch of this tenant, and no branch id
    anywhere, is using yet. Like the tenant code, nobody has to invent one."""
    n = organization.branches.count() + 1
    while Branch.objects.filter(
        Q(id=f'{organization.code}-b{n}') | Q(organization=organization, code=f'b{n}'),
    ).exists():
        n += 1
    return f'b{n}'


def provision_organization(
    *, code=None, name_zh, name_ja,
    admin_account=None, admin_password=None,
    branch_code=None, branch_name_zh=None, branch_name_ja=None,
):
    """Atomically creates an Organization plus, optionally, its first branch
    and first business admin — the one place this logic lives, shared by
    `manage.py provision_organization` and the platform super admin's
    "new tenant" UI action.

    `code` and `branch_code` are generated when omitted. The branch is an
    all-or-nothing group — both names, or none of it — and so is the admin
    (account + password).
    """
    if code and Organization.objects.filter(code=code).exists():
        raise ProvisionError('organization-code-already-exists')

    has_branch = any((branch_code, branch_name_zh, branch_name_ja))
    if has_branch and not (branch_name_zh and branch_name_ja):
        raise ProvisionError('branch-fields-incomplete')

    admin_args = (admin_account, admin_password)
    if any(admin_args) and not all(admin_args):
        raise ProvisionError('admin-fields-incomplete')

    if admin_account and User.objects.filter(username=admin_account).exists():
        raise ProvisionError('admin-account-already-exists')

    if admin_password:
        try:
            validate_password(admin_password, user=User(username=admin_account, first_name=admin_account))
        except DjangoValidationError as exc:
            raise ProvisionError(f'admin-password-invalid: {"; ".join(exc.messages)}')

    with transaction.atomic():
        organization = Organization.objects.create(
            code=code or _generate_code('org', lambda c: Organization.objects.filter(code=c).exists()),
            name_zh=name_zh, name_ja=name_ja,
        )

        branch = None
        if has_branch:
            branch_code = branch_code or _next_branch_code(organization)
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


def create_branch_for_organization(organization, *, code=None, name_zh, name_ja):
    """Same seeding a chain's own admin gets from BranchViewSet.perform_create
    — the platform super admin reaches the same path when helping a tenant
    that can't (or shouldn't have to) do it themselves. `code` is generated
    when omitted."""
    code = code or _next_branch_code(organization)
    branch = Branch.objects.create(
        id=f'{organization.code}-{code}', organization=organization,
        code=code, name_zh=name_zh, name_ja=name_ja,
    )
    seed_default_payment_methods(branch)
    seed_default_schedule_setting(branch)
    return branch
