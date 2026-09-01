from django.core.management.base import BaseCommand

from promotions.services import expire_stale_points


class Command(BaseCommand):
    help = (
        'Zero the points balance of any customer with no points activity for '
        "their campaign's points_expire_months (default 12), logging an "
        "'expire' row in the ledger. Idempotent; intended to run daily from "
        'cron.'
    )

    def handle(self, *args, **options):
        result = expire_stale_points()
        self.stdout.write(self.style.SUCCESS(
            f"expired {result['points']} points across {result['customers']} customers"
        ))
