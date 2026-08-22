from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        BRANCH = 'branch', 'Branch'
        STAFF = 'staff', 'Staff'

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.BRANCH)
    # Every business user (admin/branch/staff) belongs to exactly one
    # Organization — required for all of them, including admin, which is
    # why this can't just be derived from `branch` (admin has none).
    # Platform-level cross-tenant access is Django's own
    # is_superuser/is_staff, never this business role field.
    organization = models.ForeignKey('organizations.Organization', on_delete=models.PROTECT, related_name='users')
    branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users',
        help_text='Required for branch/staff-role accounts; unused for admins, who see all branches.',
    )
    staff_member = models.OneToOneField(
        'staff.StaffMember',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='user_account',
        help_text='Set only for role=staff accounts — links the login to the employee record it represents.',
    )

    def __str__(self):
        return self.username


class UserPreference(models.Model):
    """One row per account — UI preferences that used to live in
    localStorage now live server-side so they follow the account across
    devices/browsers, and so the frontend never has to reach into
    localStorage for anything beyond auth tokens."""

    class Locale(models.TextChoices):
        ZH = 'zh', 'Chinese'
        JA = 'ja', 'Japanese'

    class Theme(models.TextChoices):
        LIGHT = 'light', 'Light'
        DARK = 'dark', 'Dark'

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='preference')
    locale = models.CharField(max_length=2, choices=Locale.choices, default=Locale.ZH)
    theme = models.CharField(max_length=5, choices=Theme.choices, default=Theme.LIGHT)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.user_id} preference'
