from django.core.management.base import BaseCommand
from django.db import transaction

from purchasing.models import PurchaseRecord
from purchasing.utils import normalize_item_name


class Command(BaseCommand):
    help = (
        'One-off data fix: recomputes item_name_normalized for every '
        'PurchaseRecord where it is blank. import_purchases_2026 (and any '
        'other bulk_create-based import) never populates this field — it '
        'is only ever set inside PurchaseRecord.save(), which bulk_create '
        'does not call — so every bulk-imported row has been silently '
        'invisible to price history, cross-supplier comparison, and the '
        'month-over-month price-change comparison. Idempotent: only '
        'touches rows currently blank, safe to re-run.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report how many rows would be fixed without writing anything.',
        )

    def handle(self, *args, **options):
        stale = PurchaseRecord.objects.filter(item_name_normalized='')
        total = stale.count()
        if options['dry_run']:
            self.stdout.write(f'[DRY RUN] {total} record(s) have a blank item_name_normalized.')
            return

        updated = 0
        with transaction.atomic():
            for record in stale.iterator():
                record.item_name_normalized = normalize_item_name(record.item_name)
                record.save(update_fields=['item_name_normalized'])
                updated += 1

        self.stdout.write(self.style.SUCCESS(f'Backfilled item_name_normalized on {updated} of {total} record(s).'))
