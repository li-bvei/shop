from django.conf import settings
from django.db import models


class DabingStore(models.Model):
    """A store used only by the 大饼 lottery workflow.

    This is deliberately separate from the operational Branch model: the
    source sheet has its own store names and the lottery data must not be
    accidentally mixed into daily operations or payroll.
    """

    organization = models.ForeignKey('organizations.Organization', on_delete=models.PROTECT, related_name='dabing_stores')
    name = models.CharField(max_length=100)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order', 'id']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'name'], name='unique_dabing_store_per_organization'),
        ]

    def __str__(self):
        return self.name


class DabingPerson(models.Model):
    """Person master data for 大饼 only."""

    organization = models.ForeignKey('organizations.Organization', on_delete=models.PROTECT, related_name='dabing_people')
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=30, blank=True)
    contact = models.CharField(max_length=160, blank=True)
    birthday = models.DateField(null=True, blank=True)
    mobile_model = models.CharField(max_length=100, blank=True)
    note = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name', 'id']
        indexes = [
            models.Index(fields=['organization', 'name'], name='lottery_dab_organiz_6bbef2_idx'),
            models.Index(fields=['organization', 'phone'], name='lottery_dab_organiz_7c2f5a_idx'),
        ]

    def __str__(self):
        return self.name


class DabingRecord(models.Model):
    """One 大饼 entry. Store and time belong to the record, not the person."""

    organization = models.ForeignKey('organizations.Organization', on_delete=models.PROTECT, related_name='dabing_records')
    store = models.ForeignKey(DabingStore, on_delete=models.PROTECT, related_name='records')
    person = models.ForeignKey(DabingPerson, on_delete=models.PROTECT, related_name='records')
    draw_date = models.DateField()
    draw_time = models.CharField(max_length=30, blank=True)
    phone_snapshot = models.CharField(max_length=30, blank=True)
    contact_snapshot = models.CharField(max_length=160, blank=True)
    mobile_model_snapshot = models.CharField(max_length=100, blank=True)
    birthday_snapshot = models.DateField(null=True, blank=True)
    source_sheet = models.CharField(max_length=100, blank=True)
    source_row = models.PositiveIntegerField(null=True, blank=True)
    source_payload = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_dabing_records')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-draw_date', 'store__sort_order', 'draw_time', 'id']
        indexes = [
            models.Index(fields=['organization', 'draw_date'], name='lottery_dab_organiz_1afcde_idx'),
            models.Index(fields=['organization', 'store', 'draw_date'], name='lottery_dab_organiz_21f2e9_idx'),
        ]


class KyotoPerson(models.Model):
    """Person master data for 京都愛電王 only."""

    organization = models.ForeignKey('organizations.Organization', on_delete=models.PROTECT, related_name='kyoto_people')
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=30, blank=True)
    note = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name', 'id']
        indexes = [
            models.Index(fields=['organization', 'name'], name='lottery_kyo_organiz_4c74c7_idx'),
            models.Index(fields=['organization', 'phone'], name='lottery_kyo_organiz_5f5acd_idx'),
        ]

    def __str__(self):
        return self.name


class KyotoDrawBatch(models.Model):
    """A Kyoto draw period and its publication date."""

    organization = models.ForeignKey('organizations.Organization', on_delete=models.PROTECT, related_name='kyoto_draw_batches')
    draw_start_date = models.DateField()
    draw_end_date = models.DateField()
    publish_date = models.DateField()
    label = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-draw_start_date', '-id']
        indexes = [
            models.Index(fields=['organization', 'publish_date'], name='lottery_kyo_organiz_17d449_idx'),
            models.Index(fields=['organization', 'draw_start_date'], name='lottery_kyo_organiz_3d1d13_idx'),
        ]

    @property
    def display_label(self):
        return self.label or f'{self.draw_start_date:%Y-%m-%d}〜{self.draw_end_date:%Y-%m-%d}'


class KyotoRecord(models.Model):
    """One 京都愛電王 winner tied to a draw batch."""

    organization = models.ForeignKey('organizations.Organization', on_delete=models.PROTECT, related_name='kyoto_records')
    batch = models.ForeignKey(KyotoDrawBatch, on_delete=models.PROTECT, related_name='records')
    person = models.ForeignKey(KyotoPerson, on_delete=models.PROTECT, related_name='records')
    phone_snapshot = models.CharField(max_length=30, blank=True)
    quantity = models.PositiveIntegerField(null=True, blank=True)
    source_sheet = models.CharField(max_length=100, blank=True)
    source_row = models.PositiveIntegerField(null=True, blank=True)
    source_payload = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_kyoto_records')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-batch__publish_date', 'person__name', 'id']
        indexes = [
            models.Index(fields=['organization', 'batch'], name='lottery_kyo_organiz_7a1db4_idx'),
        ]
