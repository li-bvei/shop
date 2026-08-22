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
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return self.name_zh
