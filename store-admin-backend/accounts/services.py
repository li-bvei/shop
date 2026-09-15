from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError

from .models import User


def validate_new_password(password, user=None):
    """Runs Django's configured AUTH_PASSWORD_VALIDATORS (length, common-
    password list, not-all-numeric, not-too-similar-to-username/name) —
    every place in this app that sets a password (self-service change,
    admin reset, account creation, platform reset) must go through this
    instead of its own ad-hoc length check, or the validators in settings
    are silently dead code. `user` is optional (and needn't be saved yet)
    — only used by the similarity check, when there's an account to
    compare against."""
    try:
        validate_password(password, user=user)
    except DjangoValidationError as exc:
        raise ValidationError({'password': list(exc.messages)})


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


def guard_account_deletion(target, *, acting_user):
    """Raise if deleting `target` isn't allowed. Shared by the org-admin
    account screen (UserViewSet.perform_destroy) and the platform
    (super-admin) one."""
    if target == acting_user:
        raise ValidationError('cannot delete the account you are currently logged in as.')
    if target.role == User.Role.ADMIN:
        other_admins = User.objects.filter(
            role=User.Role.ADMIN, organization_id=target.organization_id,
        ).exclude(pk=target.pk)
        if not other_admins.exists():
            raise ValidationError('at least one admin account must remain.')
