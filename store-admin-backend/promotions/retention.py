"""APPI retention cleanup — erase customers with no activity for the
retention window (default 2 years, 打卡与抽奖实施方案.md §15 decision 13).
Same de-identification as an explicit "delete my data" request: the
customer row goes, the operational rows stay but detached.
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Customer
from .services import _deidentify_and_delete

DEFAULT_RETENTION_MONTHS = 24


def retention_months() -> int:
    return int(getattr(settings, 'PROMOTIONS_CUSTOMER_RETENTION_MONTHS', DEFAULT_RETENTION_MONTHS))


def purge_stale_customers(*, now=None, months=None, dry_run=False) -> dict:
    now = now or timezone.now()
    months = months or retention_months()
    cutoff = now - timedelta(days=months * 30)

    stale = Customer.objects.filter(
        Q(last_seen_at__lt=cutoff) | Q(last_seen_at__isnull=True, first_seen_at__lt=cutoff),
    ).order_by('id')

    if dry_run:
        return {'months': months, 'cutoff': cutoff.date().isoformat(), 'would_purge': stale.count()}

    purged = 0
    for customer_id in list(stale.values_list('id', flat=True)):
        with transaction.atomic():
            customer = Customer.objects.select_for_update().filter(pk=customer_id).first()
            if not customer:
                continue
            _deidentify_and_delete(customer, void_reason='retention cleanup (APPI)')
            purged += 1

    return {'months': months, 'cutoff': cutoff.date().isoformat(), 'purged': purged}
