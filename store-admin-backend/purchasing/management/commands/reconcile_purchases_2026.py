import json
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from branches.models import Branch
from purchasing.models import PurchaseRecord, Supplier
from purchasing.utils import normalize_item_name

DATA_FILE = Path(__file__).parent / 'import_data' / 'order_form_2026.json'
BRANCH_ID = 'shinsaibashi'

# The user has already hand-entered/corrected this date directly in the live
# system after the order-form spreadsheet was last exported — it must never
# be touched by this command, in either direction. Every row parsed from the
# spreadsheet for this date is excluded up front, so nothing on this date is
# ever counted as "missing" or inserted.
PROTECTED_DATE = '2026-09-13'


def normalize_supplier_name(name):
    import re
    import unicodedata
    normalized = unicodedata.normalize('NFKC', name or '')
    return re.sub(r'\s+', '', normalized).strip()


def dec_qty(v):
    # PurchaseRecord.quantity is DecimalField(decimal_places=2). The
    # spreadsheet sometimes carries more precision than that (e.g. 2.885kg)
    # — MySQL rounds any such value on insert (half-up/away-from-zero), so
    # this must round it the same way *before* comparing against the DB,
    # or every fractional-kg item looks "missing" and gets duplicated even
    # though it's already there, just stored rounded.
    return Decimal(str(v)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def dec_price(v):
    # unit_price is DecimalField(decimal_places=0).
    return Decimal(str(v)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)


class Command(BaseCommand):
    help = (
        'One-off reconciliation: compares the user-provided 2026注文書.xlsm '
        'order-form spreadsheet (every row across its 1月-9月 sheets) against '
        'every existing shinsaibashi PurchaseRecord, and inserts only the '
        'rows genuinely missing from the database. Never updates or deletes '
        'an existing row — this only ever adds. Matching key is (date, '
        'supplier, normalized item name, quantity, unit price) compared as a '
        'multiset: if the spreadsheet has the same combination more times '
        f'than the database does, the deficit is inserted. {PROTECTED_DATE} '
        'is entirely excluded from the spreadsheet side (see PROTECTED_DATE) '
        'so nothing on that date is ever added, changed, or removed. '
        'Idempotent: re-running after a successful (non-dry-run) pass finds '
        'nothing left to insert, since the database side of the comparison '
        'is re-read fresh every run.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be inserted without writing anything.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        branch = Branch.objects.get(id=BRANCH_ID)
        rows = json.loads(DATA_FILE.read_text(encoding='utf-8'))

        excel_rows = [r for r in rows if r['date'] != PROTECTED_DATE]
        protected_skipped = len(rows) - len(excel_rows)

        # Resolve every distinct supplier name against existing Supplier rows
        # — without creating anything yet. A name with no match is given a
        # per-name placeholder key instead: harmless for the diff (such a
        # supplier has zero existing PurchaseRecord rows by definition, so
        # every key built from it always reports as a deficit, the same as
        # a real but brand-new pk would), and it means supplier creation can
        # be deferred into the same atomic block as the record inserts below
        # — no risk of a supplier landing in the DB while the run that
        # needed it then fails partway through.
        supplier_names = sorted({r['supplier'] for r in excel_rows})
        suppliers_by_norm_name = {}
        for s in Supplier.objects.filter(organization=branch.organization):
            suppliers_by_norm_name.setdefault(normalize_supplier_name(s.name), s)

        supplier_key_by_name = {}
        new_supplier_names = []
        for name in supplier_names:
            existing = suppliers_by_norm_name.get(normalize_supplier_name(name))
            if existing:
                supplier_key_by_name[name] = existing.pk
            else:
                supplier_key_by_name[name] = f'new:{name}'
                new_supplier_names.append(name)

        def excel_key(r):
            return (
                r['date'], supplier_key_by_name[r['supplier']],
                normalize_item_name(r['item_name']), dec_qty(r['quantity']), dec_price(r['unit_price']),
            )

        # DB side is read fresh every run — this is what makes the command
        # safe to re-run: rows it already inserted count against the excel
        # side next time, so the deficit converges to zero.
        db_rows = PurchaseRecord.objects.filter(branch=branch).values(
            'date', 'supplier_id', 'item_name_normalized', 'quantity', 'unit_price',
        )
        db_counter = Counter(
            (
                r['date'].isoformat(), r['supplier_id'], r['item_name_normalized'],
                r['quantity'], r['unit_price'],
            )
            for r in db_rows
        )

        excel_counter = Counter()
        excel_first_seen = {}
        for r in excel_rows:
            key = excel_key(r)
            excel_counter[key] += 1
            excel_first_seen.setdefault(key, r)

        to_insert = []
        for key, ecount in excel_counter.items():
            deficit = ecount - db_counter.get(key, 0)
            if deficit > 0:
                sample = excel_first_seen[key]
                to_insert.extend([sample] * deficit)

        by_month = Counter(r['date'][:7] for r in to_insert)
        total_amount = sum(dec_qty(r['quantity']) * dec_price(r['unit_price']) for r in to_insert)

        prefix = '[DRY RUN] ' if dry_run else ''
        self.stdout.write(f'{prefix}Spreadsheet rows: {len(rows)} ({protected_skipped} on {PROTECTED_DATE} excluded)')
        if new_supplier_names:
            self.stdout.write(self.style.WARNING(
                f'{prefix}New suppliers {"would be " if dry_run else ""}created: {new_supplier_names}',
            ))
        self.stdout.write(f'{prefix}Rows to insert: {len(to_insert)}, total amount {total_amount:,}')
        for month in sorted(by_month):
            self.stdout.write(f'  {month}: {by_month[month]}')

        if dry_run:
            return

        # Supplier creation and the record inserts that depend on it share
        # one atomic block — if bulk_create fails partway through, the new
        # supplier(s) roll back with it instead of being left behind
        # unreferenced by anything.
        with transaction.atomic():
            today = timezone.localdate()
            for name in new_supplier_names:
                supplier = Supplier.objects.create(organization=branch.organization, name=name)
                suppliers_by_norm_name[normalize_supplier_name(name)] = supplier

            def resolve_supplier(name):
                return suppliers_by_norm_name[normalize_supplier_name(name)]

            records = [
                PurchaseRecord(
                    date=r['date'], branch=branch, supplier=resolve_supplier(r['supplier']),
                    item_name=r['item_name'], item_name_normalized=normalize_item_name(r['item_name']),
                    quantity=dec_qty(r['quantity']), unit_price=dec_price(r['unit_price']),
                    amount=dec_qty(r['quantity']) * dec_price(r['unit_price']),
                    note=r.get('note') or '',
                )
                for r in to_insert
            ]
            PurchaseRecord.objects.bulk_create(records)

        self.stdout.write(self.style.SUCCESS(
            f'Inserted {len(to_insert)} purchase records ({today.isoformat()} run) '
            f'and created {len(new_supplier_names)} new supplier(s).',
        ))
