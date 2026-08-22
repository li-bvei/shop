import json
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from branches.models import Branch
from purchasing.models import PurchaseRecord, Supplier

DATA_FILE = Path(__file__).parent / 'import_data' / 'purchases_2026.json'
BRANCH_ID = 'shinsaibashi'


class Command(BaseCommand):
    help = (
        'One-off import of real 2026 purchase data (Jan-Aug, ~4266 rows) '
        'extracted from the user-provided 2026注文書.xlsm order-form '
        'spreadsheet. Appends to whatever purchase records already exist '
        '(e.g. the 2023 historical import) rather than replacing them.'
    )

    def handle(self, *args, **options):
        branch = Branch.objects.get(id=BRANCH_ID)
        records = json.loads(DATA_FILE.read_text(encoding='utf-8'))

        supplier_names = sorted({r['supplier'] for r in records})
        suppliers_by_name = {}
        created_suppliers = 0
        for name in supplier_names:
            supplier, created = Supplier.objects.get_or_create(name=name)
            suppliers_by_name[name] = supplier
            if created:
                created_suppliers += 1

        with transaction.atomic():
            purchase_records = [
                PurchaseRecord(
                    date=r['date'],
                    branch=branch,
                    supplier=suppliers_by_name[r['supplier']],
                    item_name=r['item_name'],
                    quantity=Decimal(str(r['quantity'])),
                    unit_price=Decimal(str(r['unit_price'])),
                    amount=Decimal(str(r['quantity'])) * Decimal(str(r['unit_price'])),
                    note=r['note'],
                )
                for r in records
            ]
            PurchaseRecord.objects.bulk_create(purchase_records)

        self.stdout.write(self.style.SUCCESS(
            f'Created {created_suppliers} new suppliers, '
            f'imported {len(purchase_records)} purchase records into {branch.name_zh}.'
        ))
