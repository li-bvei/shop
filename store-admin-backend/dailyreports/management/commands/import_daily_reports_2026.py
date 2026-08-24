import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from branches.models import Branch
from dailyreports.models import DailyReport
from paymentmethods.models import PaymentMethodDef
from staff.models import StaffMember

DATA_FILE = Path(__file__).parent / 'import_data' / 'daily_reports_2026.json'
BRANCH_ID = 'shinsaibashi'

# The four payment methods the spreadsheet used that aren't in this app's
# default lineup (see paymentmethods.models.DEFAULT_METHOD_SPECS) — these
# were added as custom PaymentMethodDef rows for shinsaibashi (via Django
# shell, matching the frontend's own add-custom-method flow) before this
# command was written. Custom rows have a random `code`, so they're
# resolved by their exact custom_name text instead.
CUSTOM_CODE_TO_NAME = {
    'gurunaviCoupon': 'ぐるなび金券',
    'hpCoupon': 'HP金券',
    'mealVoucher': '食事券',
    'prepaidCard': 'プリペイドカード',
}


class Command(BaseCommand):
    help = (
        'One-off import of real Jan-Aug 2026 daily reports for 心斎橋本店, '
        'extracted from the user-provided monthly 売上日報 spreadsheets '
        '(1月.xlsm .. 8月.xlsm). Each in-sheet "現金仕入れ" cash-purchase '
        'line becomes a DailyReport.expenses entry (not a PurchaseRecord — '
        'the vendor names in that table were too inconsistently written to '
        'safely match against Supplier). Idempotent: re-running updates '
        'existing rows for the same branch+date rather than duplicating.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Parse and report what would happen without writing anything.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        branch = Branch.objects.get(id=BRANCH_ID)
        records = json.loads(DATA_FILE.read_text(encoding='utf-8'))

        methods_by_code = {m.code: m for m in PaymentMethodDef.objects.filter(branch=branch)}
        methods_by_name = {m.custom_name: m for m in PaymentMethodDef.objects.filter(branch=branch) if m.custom_name}

        created_count = 0
        updated_count = 0
        skipped_payment_labels = set()

        with transaction.atomic():
            # Every 記入者 name the spreadsheets reference, resolved to a
            # real StaffMember up front — none of these people had a staff
            # record yet (only demo placeholders existed), so this creates
            # them. Kept inside the same atomic block as everything else
            # so --dry-run's rollback below also undoes this.
            person_names = set()
            for r in records:
                raw = r.get('person_in_charge_raw', '')
                if raw:
                    person_names.update(raw.replace('　', ' ').split())

            staff_by_name = {}
            created_staff = 0
            for name in sorted(person_names):
                staff, created = StaffMember.objects.get_or_create(branch=branch, name=name)
                staff_by_name[name] = staff
                if created:
                    created_staff += 1

            for r in records:
                payment_amounts = {}
                for code, amount in r['payment_amounts'].items():
                    method = methods_by_code.get(code) or methods_by_name.get(CUSTOM_CODE_TO_NAME.get(code, ''))
                    if not method:
                        skipped_payment_labels.add(code)
                        continue
                    payment_amounts[str(method.id)] = amount

                person = None
                raw_name = r.get('person_in_charge_raw', '')
                if raw_name:
                    first_name = raw_name.replace('　', ' ').split()[0]
                    person = staff_by_name.get(first_name)

                defaults = {
                    'person_in_charge': person,
                    'total_revenue': r['total_revenue'],
                    'total_customers': r['total_customers'],
                    'group_count': r['group_count'],
                    'morning_revenue': r['morning_revenue'],
                    'morning_customers': r['morning_customers'],
                    'morning_group_count': r['morning_group_count'],
                    'payment_amounts': payment_amounts,
                    'expenses': r['expenses'],
                }

                if dry_run:
                    exists = DailyReport.objects.filter(branch=branch, date=r['date']).exists()
                    if exists:
                        updated_count += 1
                    else:
                        created_count += 1
                    continue

                _, created = DailyReport.objects.update_or_create(
                    branch=branch, date=r['date'], defaults=defaults,
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS(
            f'{"[DRY RUN] " if dry_run else ""}'
            f'{created_count} created, {updated_count} updated, {len(records)} total day records.'
        ))
        self.stdout.write(f'Staff resolved: {len(staff_by_name)} ({created_staff} newly created) — {sorted(staff_by_name)}')
        if skipped_payment_labels:
            self.stdout.write(self.style.WARNING(
                f'Payment codes with no matching PaymentMethodDef (amounts dropped): {sorted(skipped_payment_labels)}'
            ))
