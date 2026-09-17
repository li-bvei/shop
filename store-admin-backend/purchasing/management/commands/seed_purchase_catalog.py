from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from branches.models import Branch
from purchasing.models import PurchaseItemSeed, PurchaseRecord
from purchasing.utils import normalize_item_name


class Command(BaseCommand):
    help = 'Copy a source branch purchase-item catalogue to another branch without creating financial transactions.'

    def add_arguments(self, parser):
        parser.add_argument('--source', required=True)
        parser.add_argument('--target', required=True)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        try:
            source = Branch.objects.get(pk=options['source'])
            target = Branch.objects.get(pk=options['target'])
        except Branch.DoesNotExist as exc:
            raise CommandError(f'Branch not found: {exc}')
        if source.organization_id != target.organization_id:
            raise CommandError('Source and target branches must belong to the same organization.')
        if source.pk == target.pk:
            raise CommandError('Source and target branches must be different.')

        # Latest source transaction wins for each supplier + normalized item.
        catalogue = {}
        rows = PurchaseRecord.objects.filter(branch=source).order_by('-date', '-id').values(
            'supplier_id', 'item_name', 'item_name_normalized', 'unit_price',
        )
        for row in rows.iterator():
            normalized = row['item_name_normalized'] or normalize_item_name(row['item_name'])
            row['item_name_normalized'] = normalized
            key = (row['supplier_id'], normalized)
            catalogue.setdefault(key, row)

        existing = {
            (row.supplier_id, row.item_name_normalized): row
            for row in PurchaseItemSeed.objects.filter(branch=target)
        }
        creates = []
        updates = []
        for key, row in catalogue.items():
            seed = existing.get(key)
            if seed is None:
                creates.append(PurchaseItemSeed(
                    branch=target,
                    supplier_id=row['supplier_id'],
                    item_name=row['item_name'],
                    item_name_normalized=row['item_name_normalized'],
                    last_unit_price=row['unit_price'],
                ))
            elif seed.item_name != row['item_name'] or seed.last_unit_price != row['unit_price']:
                seed.item_name = row['item_name']
                seed.last_unit_price = row['unit_price']
                updates.append(seed)

        self.stdout.write(
            f'{source.name_zh} -> {target.name_zh}: {len(catalogue)} items, '
            f'{len(creates)} create, {len(updates)} update.'
        )
        if options['dry_run']:
            self.stdout.write(self.style.WARNING('Dry run: no rows written.'))
            return
        with transaction.atomic():
            PurchaseItemSeed.objects.bulk_create(creates, ignore_conflicts=True)
            if updates:
                PurchaseItemSeed.objects.bulk_update(updates, ['item_name', 'last_unit_price'])
        self.stdout.write(self.style.SUCCESS('Purchase catalogue seeded successfully; no purchase records were created.'))
