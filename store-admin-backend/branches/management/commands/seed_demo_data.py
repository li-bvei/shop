import json
from pathlib import Path

from django.core.management.base import BaseCommand

from accounts.models import User
from branches.models import Branch
from dailyreports.models import DailyReport
from organizations.models import Organization
from paymentmethods.models import PaymentMethodDef, seed_default_payment_methods
from purchasing.models import PurchaseRecord, Supplier
from staff.models import StaffMember

DATA_DIR = Path(__file__).parent / 'seed_data'

DEFAULT_ORG_CODE = 'default-store-group'
DEFAULT_ORG_NAME_ZH = '现有店铺集团'
DEFAULT_ORG_NAME_JA = '既存店舗グループ'

STAFF_SEED = [
    ('shinsaibashi', '王偉', '店长', '090-1111-2222', 'active'),
    ('shinsaibashi', '田中', '服务员', '090-1111-3333', 'active'),
    ('shinsaibashi', '鈴木', '厨师', '090-1111-4444', 'active'),
    ('namba', '佐藤', '店长', '090-2222-1111', 'active'),
    ('namba', '李明', '收银', '090-2222-3333', 'inactive'),
    ('umeda', '山本', '店长', '090-3333-1111', 'active'),
    ('umeda', '张伟', '厨师', '090-3333-2222', 'active'),
]

# (account, password, display_name, role, branch_id)
ACCOUNT_SEED = [
    ('admin', 'admin123', '管理员', User.Role.ADMIN, None),
    ('shinsaibashi01', 'shinsaibashi123', '心斋桥店', User.Role.BRANCH, 'shinsaibashi'),
    ('namba01', 'namba123', '难波店', User.Role.BRANCH, 'namba'),
    ('umeda01', 'umeda123', '梅田店', User.Role.BRANCH, 'umeda'),
]


class Command(BaseCommand):
    help = (
        'Full data migration from the frontend mock layer: branches, demo '
        'accounts, standard payment methods, staff, suppliers, the 766 real '
        'purchase records imported from the 2023 order-form spreadsheet, '
        'and a daily report seed.'
    )

    def handle(self, *args, **options):
        self.org = self.seed_organization()
        self.seed_branches()
        self.seed_payment_methods()
        self.seed_accounts()
        self.seed_staff()
        self.seed_suppliers_and_purchases()
        self.seed_daily_report()

    def seed_organization(self):
        org, _ = Organization.objects.get_or_create(
            code=DEFAULT_ORG_CODE, defaults={'name_zh': DEFAULT_ORG_NAME_ZH, 'name_ja': DEFAULT_ORG_NAME_JA},
        )
        self.stdout.write(self.style.SUCCESS(f'Seeded organization {org.code}.'))
        return org

    def seed_branches(self):
        for code, name_zh, name_ja in [
            ('shinsaibashi', '心斋桥店', '心斎橋店'),
            ('namba', '难波店', '難波店'),
            ('umeda', '梅田店', '梅田店'),
        ]:
            Branch.objects.update_or_create(
                id=code, defaults={'organization': self.org, 'code': code, 'name_zh': name_zh, 'name_ja': name_ja},
            )
        self.stdout.write(self.style.SUCCESS('Seeded 3 branches.'))

    def seed_payment_methods(self):
        for branch in Branch.objects.all():
            if not PaymentMethodDef.objects.filter(branch=branch).exists():
                seed_default_payment_methods(branch)
        self.stdout.write(self.style.SUCCESS('Seeded payment methods for every branch.'))

    def seed_accounts(self):
        for account, password, display_name, role, branch_id in ACCOUNT_SEED:
            # is_staff/is_superuser are deliberately never set here — the
            # business `admin` role is not the same thing as a Django
            # platform superuser (which would bypass Organization scoping
            # entirely via /admin/); see accounts/migrations/0005_*.
            user, created = User.objects.get_or_create(
                username=account,
                defaults={
                    'first_name': display_name,
                    'role': role,
                    'organization': self.org,
                    'branch_id': branch_id,
                },
            )
            if created:
                user.set_password(password)
                user.save()
        self.stdout.write(self.style.SUCCESS(f'Seeded {len(ACCOUNT_SEED)} accounts.'))

    def seed_staff(self):
        if StaffMember.objects.exists():
            self.stdout.write('Staff already seeded, skipped.')
            return
        StaffMember.objects.bulk_create(
            StaffMember(branch_id=branch_id, name=name, role=role, phone=phone, status=status)
            for branch_id, name, role, phone, status in STAFF_SEED
        )
        self.stdout.write(self.style.SUCCESS(f'Seeded {len(STAFF_SEED)} staff members.'))

    def seed_suppliers_and_purchases(self):
        if Supplier.objects.exists():
            self.stdout.write('Suppliers/purchases already seeded, skipped.')
            return

        with open(DATA_DIR / 'suppliers.json', encoding='utf-8') as f:
            supplier_names = json.load(f)
        suppliers = [Supplier.objects.create(organization=self.org, name=name) for name in supplier_names]
        # purchases.json references suppliers as 1-indexed 'sup-N' matching
        # position in suppliers.json, from the original Excel extraction.
        supplier_by_key = {f'sup-{i + 1}': s for i, s in enumerate(suppliers)}
        self.stdout.write(self.style.SUCCESS(f'Seeded {len(suppliers)} suppliers.'))

        with open(DATA_DIR / 'purchases.json', encoding='utf-8') as f:
            purchase_rows = json.load(f)
        PurchaseRecord.objects.bulk_create(
            PurchaseRecord(
                date=row['date'],
                branch_id='shinsaibashi',
                supplier=supplier_by_key[row['supplierId']],
                item_name=row['itemName'],
                quantity=row['quantity'],
                unit_price=row['unitPrice'],
                amount=row['quantity'] * row['unitPrice'],
                note=row['note'],
            )
            for row in purchase_rows
        )
        self.stdout.write(self.style.SUCCESS(f'Seeded {len(purchase_rows)} purchase records.'))

    def seed_daily_report(self):
        if DailyReport.objects.exists():
            self.stdout.write('Daily report already seeded, skipped.')
            return

        methods = {m.code: m for m in PaymentMethodDef.objects.filter(branch_id='shinsaibashi')}
        staff = StaffMember.objects.filter(branch_id='shinsaibashi', role='店长').first()

        DailyReport.objects.create(
            branch_id='shinsaibashi',
            date='2026-08-15',
            person_in_charge=staff,
            total_revenue=138200,
            total_customers=62,
            group_count=28,
            morning_revenue=58600,
            morning_customers=34,
            morning_group_count=15,
            payment_amounts={
                str(methods['creditCard'].id): 38500,
                str(methods['paypay'].id): 24200,
                str(methods['osakaCoupon'].id): 0,
            },
            expenses=[
                {'itemName': '業務スーパー', 'amount': 980, 'purpose': '野菜'},
                {'itemName': 'コーナン', 'amount': 2200, 'purpose': '清掃用品'},
            ],
        )
        self.stdout.write(self.style.SUCCESS('Seeded 1 daily report.'))
