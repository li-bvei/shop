from django.db import models


class Branch(models.Model):
    """A physical store. `id` mirrors the slugs already used by the frontend
    (e.g. 'shinsaibashi') so existing mock data maps onto real records 1:1.
    `id` stays globally unique (changing it now would be a much riskier
    migration than it's worth) — multi-tenant uniqueness is enforced
    separately via `code`, which only has to be unique *within* an
    Organization, so two different customers can each have their own
    'shinsaibashi' without colliding."""

    id = models.SlugField(primary_key=True, max_length=50)
    organization = models.ForeignKey('organizations.Organization', on_delete=models.PROTECT, related_name='branches')
    code = models.SlugField(
        max_length=50, help_text='Unique within the Organization; may repeat across different Organizations.',
    )
    name_zh = models.CharField(max_length=100)
    name_ja = models.CharField(max_length=100)

    class Meta:
        ordering = ['id']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'code'], name='unique_branch_code_per_organization'),
        ]

    def __str__(self):
        return self.name_zh
