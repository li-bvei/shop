from django.core.management.base import BaseCommand

from promotions.retention import purge_stale_customers


class Command(BaseCommand):
    help = (
        'APPI retention cleanup: erase promotions customers with no activity '
        'for PROMOTIONS_CUSTOMER_RETENTION_MONTHS (default 24). The Customer '
        'row is removed; check-ins / spend verifications / ledger / draws are '
        'kept but detached and de-identified. Idempotent; intended for a '
        'weekly cron.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--months', type=int, default=None, help='Override the retention window.')
        parser.add_argument('--dry-run', action='store_true', help='Only report the count.')

    def handle(self, *args, **options):
        result = purge_stale_customers(months=options.get('months'), dry_run=options['dry_run'])
        if options['dry_run']:
            self.stdout.write(self.style.WARNING(
                f"[dry-run] {result['would_purge']} customers inactive since {result['cutoff']} "
                f"({result['months']}mo) would be erased"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"erased {result['purged']} customers inactive since {result['cutoff']} "
                f"({result['months']}mo)"
            ))
