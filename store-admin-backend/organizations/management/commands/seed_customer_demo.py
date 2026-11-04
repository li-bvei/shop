"""Build the customer-facing demo tenant.

This is NOT the same thing as `scheduling/seed_schedule_wage_demo.py`, which
is a DEBUG-only fixture for one branch, one fixed month and a handful of
shifts — useful for developing the scheduling screens, not for showing the
product to a prospect. That command is left exactly as it is.

Safety model, in order of importance:

 1. **A separate Organization.** Everything lives under the tenant whose
    code is DEMO_ORG_CODE. No real tenant's rows are read, written or
    counted. That single fact is what makes this safe to run on a server
    that also holds live customer data, and it is enforced structurally:
    every query below is scoped to that Organization, and --purge refuses
    to delete anything else.
 2. **Everything is labelled.** The tenant, its branches, its staff and its
    suppliers all carry DEMO_PREFIX in their display name, so a screenshot
    taken during a sales call can never be mistaken for real operating
    data, and anything left behind is identifiable at a glance.
 3. **Idempotent.** Re-running updates in place (get_or_create /
    update_or_create on natural keys) instead of duplicating. Running it
    twice produces exactly the state running it once does.
 4. **Reversible.** `--purge` deletes the demo tenant and everything under
    it, and nothing else.
 5. **Deliberate outside DEBUG.** On a production settings file the command
    refuses unless `--confirm` is passed, so it can never be triggered as a
    side effect of a deploy script.

Dates are generated RELATIVE TO TODAY (the demo always shows "this month"
and the two months before it), because a demo pinned to a fixed month shows
a prospect an empty dashboard the moment that month passes.
"""
import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from branches.models import Branch
from dailyreports.models import CashRegisterDefaults, DailyReport
from inventory.models import Product, Stock, StockTransaction
from organizations.demo import DEMO_ORG_CODE, DEMO_PREFIX
from organizations.models import Organization
from paymentmethods.models import PaymentMethodDef, seed_default_payment_methods
from purchasing.models import PurchaseRecord, Supplier
from scheduling.attendance import apply_exception_minutes
from scheduling.models import (
    ActualWorkRecord, AttendanceCorrectionRequest, AttendancePunch, SchedulePeriod, Shift, ShiftTemplate,
)
from scheduling.services import seed_default_schedule_setting
from staff.models import StaffMember
from wages.calculation import generate_wage_results
from wages.models import WageMonthlyClosing, WageRule

# A fixed seed makes every run of the demo produce the same numbers, so a
# salesperson who rehearsed on "¥412,000 on the 14th" sees that same figure
# in front of the customer. Randomness here is for *texture*, not surprise.
RANDOM_SEED = 20261101

DEMO_BRANCHES = (
    ('b1', f'{DEMO_PREFIX} 心斋桥店', f'{DEMO_PREFIX} 心斎橋店', 1.00),
    ('b2', f'{DEMO_PREFIX} 难波店', f'{DEMO_PREFIX} 難波店', 0.72),
    ('b3', f'{DEMO_PREFIX} 梅田店', f'{DEMO_PREFIX} 梅田店', 0.55),
)

# (account, password, role, branch index or None)
DEMO_ACCOUNTS = (
    ('demo-admin', 'demo-admin-2026', f'{DEMO_PREFIX} 总部管理员', User.Role.ADMIN, None),
    ('demo-branch', 'demo-branch-2026', f'{DEMO_PREFIX} 心斎橋店长', User.Role.BRANCH, 0),
    ('demo-staff', 'demo-staff-2026', f'{DEMO_PREFIX} 田中（员工）', User.Role.STAFF, 0),
)

# (name, role, work_area, employment_type, hourly_rate, transport)
DEMO_STAFF = (
    (f'{DEMO_PREFIX} 田中 太郎', '店長', 'hall', StaffMember.EmploymentType.HOURLY, 1450, 900),
    (f'{DEMO_PREFIX} 鈴木 花子', 'ホール', 'hall', StaffMember.EmploymentType.HOURLY, 1200, 700),
    (f'{DEMO_PREFIX} 佐藤 健', 'キッチン', 'kitchen', StaffMember.EmploymentType.HOURLY, 1350, 800),
    (f'{DEMO_PREFIX} 李 明', 'キッチン', 'kitchen', StaffMember.EmploymentType.TEMPORARY, 1250, 0),
    (f'{DEMO_PREFIX} 山本 美咲', 'ホール', 'hall', StaffMember.EmploymentType.HOURLY, 1200, 600),
    (f'{DEMO_PREFIX} 王 偉', 'マネージャー', 'hall', StaffMember.EmploymentType.REGULAR_MONTHLY, 0, 0),
)

DEMO_SUPPLIERS = (
    (f'{DEMO_PREFIX} 大阪中央青果', '野菜・果物', 0.30),
    (f'{DEMO_PREFIX} 浪速鮮魚', '鮮魚', 0.26),
    (f'{DEMO_PREFIX} 関西精肉卸', '精肉', 0.22),
    (f'{DEMO_PREFIX} 近畿酒販', '酒類・飲料', 0.14),
    (f'{DEMO_PREFIX} 日用品サプライ浪速', '消耗品', 0.08),
)

DEMO_PRODUCTS = (
    (f'{DEMO_PREFIX} 生ビール中ジョッキ', 'ドリンク', '杯', 650, 190, 40),
    (f'{DEMO_PREFIX} ハイボール', 'ドリンク', '杯', 550, 150, 40),
    (f'{DEMO_PREFIX} 刺身盛り合わせ', '料理', '皿', 1800, 820, 10),
    (f'{DEMO_PREFIX} 唐揚げ', '料理', '皿', 680, 240, 20),
    (f'{DEMO_PREFIX} 季節の野菜天ぷら', '料理', '皿', 980, 350, 15),
    (f'{DEMO_PREFIX} おしぼり', '消耗品', '個', 0, 12, 200),
)

PURCHASE_ITEMS = {
    '野菜・果物': ('玉ねぎ', 'キャベツ', 'レタス', 'トマト', 'じゃがいも'),
    '鮮魚': ('真鯛', 'ぶり', 'サーモン', 'えび', 'まぐろ'),
    '精肉': ('鶏もも肉', '豚バラ', '牛肩ロース', '鶏むね肉'),
    '酒類・飲料': ('生ビール樽', '焼酎', '日本酒', 'ウーロン茶'),
    '消耗品': ('おしぼり', '割り箸', '洗剤', 'ゴミ袋'),
}

def months_before(first_of_month, months):
    """The 1st of the month `months` calendar months before `first_of_month`.

    Counted in months, not in days: subtracting `31 * months` days lands in
    the wrong month whenever a shorter month is involved (on 2026-03-01,
    three 31-day steps reach 2025-12-29 -> December, when the answer is
    January), and the demo would then silently generate one month too few.
    """
    index = first_of_month.year * 12 + (first_of_month.month - 1) - months
    return date(index // 12, index % 12 + 1, 1)


EXPENSE_ITEMS = (
    ('タクシー代', '深夜スタッフ送り'),
    ('備品購入', 'グラス補充'),
    ('クリーニング', '制服'),
    ('修繕費', '厨房換気扇'),
)


class Command(BaseCommand):
    help = (
        'Idempotently build (or --purge) the customer demo tenant: an isolated '
        'Organization with three branches, staff, suppliers, products, three '
        'months of daily reports, purchases, inventory, schedules, attendance '
        '(including clock punches and a pending correction request) and wages. '
        'Never touches any other tenant.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--purge', action='store_true',
            help='Delete the demo tenant and everything under it. Deletes nothing else.',
        )
        parser.add_argument(
            '--confirm', action='store_true',
            help='Required when DEBUG is False, so a deploy script cannot trigger this by accident.',
        )
        parser.add_argument(
            '--months', type=int, default=3,
            help='How many months of operating history to generate, ending today (default 3).',
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options['confirm']:
            raise CommandError(
                'refusing to run outside DEBUG without --confirm. This command only ever touches the '
                f'"{DEMO_ORG_CODE}" tenant, but generating demo data on a production server must be deliberate.',
            )

        if options['purge']:
            self.purge()
            return

        random.seed(RANDOM_SEED)
        with transaction.atomic():
            org = self.seed_organization()
            branches = self.seed_branches(org)
            accounts = self.seed_accounts(org, branches)
            staff = self.seed_staff(branches)
            self.link_staff_account(accounts, branches, staff)
            suppliers = self.seed_suppliers(org)
            self.seed_products_and_stock(org, branches, accounts)
            self.seed_operations(branches, staff, suppliers, accounts, options['months'])
            self.seed_attendance_and_wages(branches, staff, accounts)

        self.stdout.write(self.style.SUCCESS(
            f'demo tenant "{DEMO_ORG_CODE}" ready: '
            f'{len(branches)} branches, {sum(len(v) for v in staff.values())} staff, '
            f'{DailyReport.objects.filter(branch__organization__code=DEMO_ORG_CODE).count()} daily reports, '
            f'{PurchaseRecord.objects.filter(branch__organization__code=DEMO_ORG_CODE).count()} purchases.',
        ))
        self.stdout.write('demo logins: ' + ', '.join(f'{a}/{p}' for a, p, _, _, _ in DEMO_ACCOUNTS))

    # -- purge -------------------------------------------------------------

    def purge(self):
        org = Organization.objects.filter(code=DEMO_ORG_CODE).first()
        if not org:
            self.stdout.write('nothing to purge — demo tenant does not exist.')
            return
        # Scoped by Organization, so this can never reach another tenant's
        # rows however many of them exist on the same database.
        branch_ids = list(org.branches.values_list('id', flat=True))
        with transaction.atomic():
            # Deleted explicitly, in dependency order, because several
            # models hang off Branch with on_delete=PROTECT and would
            # otherwise block the cascade from Organization.
            StockTransaction.objects.filter(branch_id__in=branch_ids).delete()
            Stock.objects.filter(branch_id__in=branch_ids).delete()
            Product.objects.filter(organization=org).delete()
            PurchaseRecord.objects.filter(branch_id__in=branch_ids).delete()
            Supplier.objects.filter(organization=org).delete()
            DailyReport.objects.filter(branch_id__in=branch_ids).delete()
            WageMonthlyClosing.objects.filter(branch_id__in=branch_ids).delete()
            AttendancePunch.objects.filter(branch_id__in=branch_ids).delete()
            AttendanceCorrectionRequest.objects.filter(branch_id__in=branch_ids).delete()
            ActualWorkRecord.objects.filter(branch_id__in=branch_ids).delete()
            Shift.objects.filter(branch_id__in=branch_ids).delete()
            SchedulePeriod.objects.filter(branch_id__in=branch_ids).delete()
            StaffMember.objects.filter(branch_id__in=branch_ids).delete()
            User.objects.filter(organization=org).delete()
            # Branch.organization is on_delete=PROTECT, so the branches have
            # to go before the Organization — deleting the tenant first
            # raises ProtectedError instead of cascading.
            Branch.objects.filter(organization=org).delete()
            org.delete()
        self.stdout.write(self.style.SUCCESS(f'purged demo tenant "{DEMO_ORG_CODE}" and {len(branch_ids)} branches.'))

    # -- build -------------------------------------------------------------

    def seed_organization(self):
        org, _ = Organization.objects.update_or_create(
            code=DEMO_ORG_CODE,
            defaults={'name_zh': f'{DEMO_PREFIX} 演示餐饮集团', 'name_ja': f'{DEMO_PREFIX} デモ飲食グループ'},
        )
        return org

    def seed_branches(self, org):
        branches = []
        for code, name_zh, name_ja, _scale in DEMO_BRANCHES:
            branch, _ = Branch.objects.update_or_create(
                id=f'{DEMO_ORG_CODE}-{code}',
                defaults={'organization': org, 'code': code, 'name_zh': name_zh, 'name_ja': name_ja},
            )
            # seed_default_payment_methods is a one-shot bulk_create for a
            # NEWLY created branch (see its docstring) — calling it again on
            # a re-run violates the unique (branch, code) constraint. Gated
            # on "does this branch have any yet" rather than on the
            # get_or_create `created` flag, so a half-finished earlier run
            # still converges instead of staying broken.
            if not PaymentMethodDef.objects.filter(branch=branch).exists():
                seed_default_payment_methods(branch)
            seed_default_schedule_setting(branch)
            CashRegisterDefaults.objects.get_or_create(branch=branch, defaults={'expected_total': 130000})
            branches.append(branch)
        return branches

    def seed_accounts(self, org, branches):
        accounts = {}
        for username, password, display_name, role, branch_index in DEMO_ACCOUNTS:
            branch = branches[branch_index] if branch_index is not None else None
            user, created = User.objects.get_or_create(
                username=username,
                defaults={'organization': org, 'role': role, 'branch': branch, 'first_name': display_name},
            )
            # The password is reset on every run so a demo account can't drift
            # out of sync with what the sales team was told it is.
            user.organization = org
            user.role = role
            user.branch = branch
            user.first_name = display_name
            user.set_password(password)
            user.save()
            accounts[role if branch_index is None else f'{role}-{branch_index}'] = user
            if created:
                self.stdout.write(f'  created demo account {username}')
        return accounts

    def seed_staff(self, branches):
        """Every branch gets the full roster; the first branch's roster is the
        one the demo script walks through."""
        by_branch = {}
        for branch in branches:
            members = []
            for name, role, area, employment_type, rate, transport in DEMO_STAFF:
                member, _ = StaffMember.objects.update_or_create(
                    branch=branch, name=f'{name}（{branch.code}）',
                    defaults={
                        'role': role, 'work_area': area, 'employment_type': employment_type,
                        'status': StaffMember.Status.ACTIVE,
                        'hire_date': date.today() - timedelta(days=400),
                        'phone': '090-0000-0000',
                    },
                )
                if rate:
                    WageRule.objects.update_or_create(
                        employee=member, effective_from=date.today() - timedelta(days=400),
                        defaults={
                            'hourly_rate': Decimal(rate),
                            'transportation_type': WageRule.TransportationType.MONTHLY,
                            'transportation_amount': Decimal(transport),
                            'note': 'seed_customer_demo',
                        },
                    )
                members.append(member)
            by_branch[branch.id] = members
        return by_branch

    def link_staff_account(self, accounts, branches, staff):
        """Point the demo staff login at a real employee record.

        Without this the account authenticates but every employee-side
        attendance call refuses it: AttendanceScopedMixin scopes a staff
        caller by `user.staff_member_id` (none -> empty queryset) and
        `resolve_employee` raises 'this account is not linked to an employee
        record.' on write. So the one screen the staff login exists to
        demonstrate would be empty and unusable.

        Runs after seed_staff because the StaffMember has to exist first.
        Idempotent: re-running re-points the same account at the same
        employee, and `staff_member` is a OneToOneField so there is nothing
        to accumulate.
        """
        user = accounts.get(f'{User.Role.STAFF}-0')
        if user is None:
            return
        # The first branch's first employee — the same one the attendance
        # and correction-request data below is seeded for.
        member = staff[branches[0].id][0]
        if user.staff_member_id != member.id:
            user.staff_member = member
            user.save(update_fields=['staff_member'])

    def seed_suppliers(self, org):
        suppliers = []
        for name, category, share in DEMO_SUPPLIERS:
            supplier, _ = Supplier.objects.update_or_create(
                organization=org, name=name,
                defaults={'category': category, 'contact': '担当者', 'phone': '06-0000-0000'},
            )
            suppliers.append((supplier, category, share))
        return suppliers

    def seed_products_and_stock(self, org, branches, accounts):
        operator = accounts.get(User.Role.ADMIN)
        for name, category, unit, price, cost, threshold in DEMO_PRODUCTS:
            product, _ = Product.objects.update_or_create(
                organization=org, name=name,
                defaults={
                    'category': category, 'unit': unit,
                    'selling_price': Decimal(price), 'cost_price': Decimal(cost),
                    'low_stock_threshold': Decimal(threshold), 'status': Product.Status.ACTIVE,
                },
            )
            for branch in branches:
                # One product is deliberately left BELOW its low-stock
                # threshold at the first branch, so the demo has a real
                # warning to show rather than an all-green screen nobody
                # believes.
                below = (branch is branches[0] and name.endswith('刺身盛り合わせ'))
                quantity = Decimal(threshold) * (Decimal('0.4') if below else Decimal('3'))
                stock, created = Stock.objects.get_or_create(
                    branch=branch, product=product, defaults={'quantity': quantity},
                )
                if not created:
                    stock.quantity = quantity
                    stock.save()
                StockTransaction.objects.get_or_create(
                    branch=branch, product=product,
                    transaction_type=StockTransaction.TransactionType.ADJUSTMENT_IN,
                    note='seed_customer_demo',
                    defaults={'quantity': quantity, 'operator': operator},
                )

    def seed_operations(self, branches, staff, suppliers, accounts, months):
        """Daily reports + purchases across the last `months` months.

        Shaped like a real restaurant rather than a flat line: weekends are
        busier than Mondays, there is a slow stretch and a good stretch, and
        the payment mix shifts. A demo whose chart is a straight line is a
        demo nobody believes.
        """
        today = date.today()
        # `months` counts calendar months INCLUDING the current one, so
        # months=3 means this month plus the two before it.
        start = months_before(today.replace(day=1), months - 1)
        updated_by = accounts.get(User.Role.ADMIN)

        for branch in branches:
            scale = next(s for code, _, _, s in DEMO_BRANCHES if f'{DEMO_ORG_CODE}-{code}' == branch.id)
            methods = list(PaymentMethodDef.objects.filter(branch=branch, active=True).order_by('sort_order'))
            members = staff[branch.id]
            current = start
            while current <= today:
                self._seed_day(branch, current, scale, methods, members, suppliers, updated_by)
                current += timedelta(days=1)

    def _seed_day(self, branch, day, scale, methods, members, suppliers, updated_by):
        weekday = day.weekday()
        # Mon=0 … Sun=6. Friday/Saturday carry a restaurant's week.
        weekday_factor = (0.82, 0.85, 0.90, 0.98, 1.30, 1.45, 1.10)[weekday]
        # A slow fortnight mid-period, so the trend chart and the automatic
        # insights have something real to point at.
        slump = 0.72 if 8 <= day.day <= 18 and day.month % 2 == 0 else 1.0
        noise = random.uniform(0.88, 1.12)

        customers = max(1, int(96 * scale * weekday_factor * slump * noise))
        avg_spend = int(random.uniform(3200, 4100))
        total_revenue = customers * avg_spend
        morning_share = random.uniform(0.28, 0.38)

        payment_amounts = {}
        remaining = total_revenue
        for index, method in enumerate(methods):
            if index == len(methods) - 1:
                payment_amounts[str(method.id)] = remaining
            else:
                share = (0.42, 0.33, 0.15, 0.06, 0.04)[index] if index < 5 else 0.0
                amount = int(total_revenue * share)
                payment_amounts[str(method.id)] = amount
                remaining -= amount
        if remaining < 0:
            payment_amounts[str(methods[-1].id)] = 0

        expenses = []
        if random.random() < 0.35:
            item, purpose = random.choice(EXPENSE_ITEMS)
            expenses.append({'itemName': item, 'amount': int(random.uniform(1500, 9000)), 'purpose': purpose})

        DailyReport.objects.update_or_create(
            branch=branch, date=day,
            defaults={
                'person_in_charge': random.choice(members),
                'total_revenue': Decimal(total_revenue),
                'total_customers': customers,
                'group_count': max(1, int(customers / random.uniform(2.0, 3.2))),
                'morning_revenue': Decimal(int(total_revenue * morning_share)),
                'morning_customers': int(customers * morning_share),
                'morning_group_count': max(1, int(customers * morning_share / 2.6)),
                'payment_amounts': payment_amounts,
                'expenses': expenses,
                'updated_by': updated_by,
            },
        )

        # Purchases land on ~3 days a week, like a real delivery schedule.
        if weekday in (0, 2, 4):
            for supplier, category, share in suppliers:
                if random.random() > 0.75:
                    continue
                item_name = random.choice(PURCHASE_ITEMS[category])
                quantity = Decimal(random.randint(2, 18))
                unit_price = Decimal(random.randint(220, 2600))
                PurchaseRecord.objects.update_or_create(
                    branch=branch, date=day, supplier=supplier, item_name=item_name,
                    defaults={
                        'quantity': quantity, 'unit_price': unit_price,
                        'amount': quantity * unit_price, 'note': 'seed_customer_demo',
                    },
                )

    def seed_attendance_and_wages(self, branches, staff, accounts):
        """The current month's schedule, attendance and a draft wage closing
        for the first branch — including the exceptions the demo needs to be
        able to talk about: a late arrival, an absence, an overnight shift,
        an unfinished punch day and one pending correction request."""
        branch = branches[0]
        members = staff[branch.id][:4]
        admin = accounts.get(User.Role.ADMIN)
        today = date.today()
        this_month = today.replace(day=1)
        # The PREVIOUS month as well as this one. A demo that only covered
        # the current month shows a single day of attendance when it is run
        # on the 1st — and none of the exceptions the demo exists to talk
        # about, since they fall on specific days of the month.
        last_month = (this_month - timedelta(days=1)).replace(day=1)

        templates = self.seed_shift_templates(branch)
        # Each employee works a rotation of the branch's templates, plus one
        # off-template time, so the demo grid shows what a time-based
        # schedule looks like: a dozen different shapes in one month, not
        # three fixed slots.
        rotation = [templates['open'], templates['lunch'], templates['through'],
                    templates['dinner'], None, templates['late'], 'custom']

        for month_start in (last_month, this_month):
            month_end = min(today, (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1))
            period, _ = SchedulePeriod.objects.get_or_create(
                branch=branch, month=month_start,
                defaults={
                    'start_date': month_start,
                    'end_date': (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1),
                    'status': SchedulePeriod.Status.PUBLISHED,
                    'published_at': timezone.now(),
                },
            )
            day = month_start
            while day <= month_end:
                for index, member in enumerate(members):
                    choice = rotation[(index * 2 + day.day) % len(rotation)]
                    if choice is None:
                        continue  # day off
                    if choice == 'custom':
                        # A one-off time typed straight into the grid.
                        start, end, break_minutes, crosses, template = time(12, 0), time(16, 30), 0, False, None
                    else:
                        template = choice
                        start, end = template.start_time, template.end_time
                        break_minutes, crosses = template.break_minutes, template.crosses_midnight
                    shift, _ = Shift.objects.update_or_create(
                        period=period, employee=member, work_date=day,
                        defaults={
                            'branch': branch, 'planned_start': start, 'planned_end': end,
                            'planned_break_minutes': break_minutes, 'crosses_midnight': crosses,
                            'template': template, 'position': member.work_area,
                        },
                    )
                    self._seed_attendance_day(branch, member, shift, day, today, admin)
                day += timedelta(days=1)

            closing, _ = WageMonthlyClosing.objects.get_or_create(
                branch=branch, month=month_start, defaults={'status': WageMonthlyClosing.Status.DRAFT},
            )
            if closing.status == WageMonthlyClosing.Status.DRAFT:
                generate_wage_results(closing)

        self._seed_pending_correction(branch, members[0], today)

    def seed_shift_templates(self, branch):
        """The demo branch's shift palette, keyed for the rotation above.

        Matched on (branch, name), so a re-run updates these rows in place
        instead of adding a second set. Any other template on the demo
        branch — the unnamed ones migration 0011 makes from the old fixed
        slots, or one added while showing the demo — is removed, so a re-run
        restores the palette the demo script describes. Shifts keep their
        times either way (Shift.template is SET_NULL)."""
        specs = {
            'open': ('オープン', time(9, 0), time(14, 0), 0, ShiftTemplate.Color.TEAL),
            'lunch': ('ランチ', time(11, 0), time(15, 30), 0, ShiftTemplate.Color.BLUE),
            'through': ('通し', time(11, 0), time(22, 0), 90, ShiftTemplate.Color.GREEN),
            'dinner': ('ディナー', time(17, 0), time(22, 30), 0, ShiftTemplate.Color.ORANGE),
            'late': ('深夜', time(22, 0), time(2, 0), 30, ShiftTemplate.Color.PURPLE),
        }
        templates = {}
        for order, (key, (name, start, end, break_minutes, color)) in enumerate(specs.items(), start=1):
            templates[key], _ = ShiftTemplate.objects.update_or_create(
                branch=branch, name=name,
                defaults={
                    'start_time': start, 'end_time': end, 'break_minutes': break_minutes,
                    'color': color, 'sort_order': order, 'active': True,
                },
            )
        ShiftTemplate.objects.filter(branch=branch).exclude(
            pk__in=[template.pk for template in templates.values()],
        ).delete()
        return templates

    def _seed_attendance_day(self, branch, member, shift, day, today, admin):
        # Deterministic "exceptions" so the demo always has the same story
        # to tell: a late arrival, an absence, and today's day still open.
        is_late = (day.day % 6 == 3)
        is_absent = (day.day % 9 == 5)
        is_today = (day == today)

        if is_absent:
            record, _ = ActualWorkRecord.objects.update_or_create(
                employee=member, work_date=day,
                defaults={
                    'branch': branch, 'shift': shift, 'absent': True,
                    'actual_start': None, 'actual_end': None, 'actual_break_minutes': 0,
                    'adjustment_reason': '体調不良', 'source': ActualWorkRecord.Source.MANUAL,
                    'status': ActualWorkRecord.Status.MANAGER_CONFIRMED,
                    'confirmed_by': admin, 'confirmed_at': timezone.now(),
                },
            )
            apply_exception_minutes(record)
            record.save(update_fields=['late_minutes', 'early_leave_minutes'])
            return

        actual_start = shift.planned_start
        if is_late:
            actual_start = time((shift.planned_start.hour + (1 if shift.planned_start.minute >= 40 else 0)) % 24,
                                 (shift.planned_start.minute + 20) % 60)

        # A late day came from the employee's punches (and was then
        # confirmed); only an on-time day is the plan's own copy. Labelling a
        # late day 'plan' would be untrue — and would be put back to the
        # planned times by the next schedule save (attendance.sync_plan_record).
        from_punches = is_today or is_late
        record, _ = ActualWorkRecord.objects.update_or_create(
            employee=member, work_date=day,
            defaults={
                'branch': branch, 'shift': shift, 'absent': False,
                'actual_start': actual_start,
                # Today is still in progress — an unfinished day is exactly
                # what a manager's "needs attention" filter is for.
                'actual_end': None if is_today else shift.planned_end,
                'crosses_midnight': shift.crosses_midnight and not is_today,
                'actual_break_minutes': shift.planned_break_minutes,
                'source': ActualWorkRecord.Source.PUNCH if from_punches else ActualWorkRecord.Source.PLAN,
                'status': (
                    ActualWorkRecord.Status.PENDING if is_today
                    else ActualWorkRecord.Status.MANAGER_CONFIRMED
                ),
                'confirmed_by': None if is_today else admin,
                'confirmed_at': None if is_today else timezone.now(),
            },
        )
        apply_exception_minutes(record)
        record.save(update_fields=['late_minutes', 'early_leave_minutes'])

        if is_today:
            # A real punch behind today's open record, so the employee
            # screen shows a live "clocked in" state rather than an empty one.
            AttendancePunch.objects.get_or_create(
                employee=member, work_date=day, kind=AttendancePunch.Kind.CLOCK_IN,
                defaults={
                    'branch': branch,
                    'punched_at': timezone.make_aware(datetime.combine(day, actual_start)),
                    'source': AttendancePunch.Source.SELF,
                },
            )

    def _seed_pending_correction(self, branch, member, today):
        """One request waiting on the manager, so the approval queue in the
        demo is not empty."""
        work_date = today - timedelta(days=2)
        AttendanceCorrectionRequest.objects.get_or_create(
            employee=member, work_date=work_date,
            status=AttendanceCorrectionRequest.Status.PENDING,
            defaults={
                'branch': branch,
                'requested_start': time(11, 0),
                'requested_end': time(22, 0),
                'requested_break_minutes': 90,
                'reason': '退勤打刻を忘れました。実際は22:00に退店しています。',
            },
        )
