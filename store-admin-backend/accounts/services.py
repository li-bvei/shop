from rest_framework.exceptions import ValidationError

from .models import User


def guard_account_deactivation(target, is_active, *, acting_user):
    """Raise if disabling `target` isn't allowed. Shared by the org-admin
    account screen and the platform (super-admin) one."""
    if is_active:
        return
    if target == acting_user:
        raise ValidationError('cannot disable the account you are currently logged in as.')
    if target.role == User.Role.ADMIN:
        other_active_admins = User.objects.filter(
            role=User.Role.ADMIN, organization_id=target.organization_id, is_active=True,
        ).exclude(pk=target.pk)
        if not other_active_admins.exists():
            raise ValidationError('at least one active admin account must remain for this organization.')
