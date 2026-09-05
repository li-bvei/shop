from django.db import models


class Organization(models.Model):
    """A tenant — one customer's whole store group. Every business user
    (admin/branch/staff), branch, and piece of shared master data
    ultimately belongs to exactly one Organization; platform-level
    cross-tenant access is Django's own is_superuser/is_staff, never the
    business `admin` role (see accounts.User.Role)."""

    code = models.SlugField(max_length=50, unique=True)
    name_zh = models.CharField(max_length=100)
    name_ja = models.CharField(max_length=100)
    # Brand logo for the customer-facing loyalty pages (register / recovery
    # / card). A URL the chain hosts themselves — the platform has no media
    # storage. Empty = the pages just show the name.
    logo_url = models.URLField(blank=True, default='')
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return self.name_zh


class OrganizationFeature(models.Model):
    """One row per (organization, feature module) the platform super admin
    has explicitly switched OFF (or back on). **No row = the feature is
    enabled** — so an existing tenant keeps everything until the operator
    touches it, and the future "pay per module" model is just a matter of
    inserting `enabled=False` rows. Every account in the organization
    (admin / branch / staff) inherits this — a branch can never re-enable
    what the platform turned off for its chain.

    The set of valid `feature` keys lives in common.features.FEATURE_REGISTRY,
    not as DB choices, so adding a module doesn't need a migration here."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='features',
    )
    feature = models.CharField(max_length=32)
    enabled = models.BooleanField(default=True)
    note = models.CharField(max_length=255, blank=True, default='')
    updated_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['organization', 'feature']
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'feature'], name='unique_org_feature',
            ),
        ]

    def __str__(self):
        return f'{self.organization_id}/{self.feature}={self.enabled}'
