"""Tests for the customer demo tenant seed.

The things that would actually hurt if they broke, in order:

  * it writes into a real customer's tenant  (DemoSeedIsolationTests)
  * --purge deletes a real customer's data   (DemoSeedPurgeTests)
  * running it twice duplicates everything   (DemoSeedIdempotencyTests)
  * it runs by accident on production        (DemoSeedGuardTests)

Everything else about the demo (how pretty the numbers are) is cosmetic.
"""
from datetime import date
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import User
from branches.models import Branch
from dailyreports.models import DailyReport
from inventory.models import Product
from organizations.demo import DEMO_ORG_CODE, DEMO_PREFIX
from organizations.management.commands.seed_customer_demo import months_before
from organizations.models import Organization
from paymentmethods.models import seed_default_payment_methods
from purchasing.models import PurchaseRecord, Supplier
from scheduling.models import ActualWorkRecord, AttendanceCorrectionRequest, Shift, ShiftTemplate
from scheduling.services import seed_default_schedule_setting
from staff.models import StaffMember


def seed(**kwargs):
    out = StringIO()
    call_command('seed_customer_demo', stdout=out, **kwargs)
    return out.getvalue()


def demo_org():
    return Organization.objects.get(code=DEMO_ORG_CODE)


class RealTenantMixin:
    """A real customer tenant sitting on the same database, with data in
    every model the seed touches — so "it only writes to the demo tenant"
    is tested against something that could actually be damaged."""

    def create_real_tenant(self):
        self.real_org = Organization.objects.create(
            code='real-customer', name_zh='真实客户', name_ja='実顧客',
        )
        self.real_branch = Branch.objects.create(
            id='real-branch', organization=self.real_org, code='b1',
            name_zh='真实店铺', name_ja='実店舗',
        )
        seed_default_payment_methods(self.real_branch)
        seed_default_schedule_setting(self.real_branch)
        self.real_user = User.objects.create_user(
            username='real-admin', password='realpass123',
            role=User.Role.ADMIN, organization=self.real_org,
        )
        self.real_staff = StaffMember.objects.create(name='真实员工', branch=self.real_branch)
        self.real_supplier = Supplier.objects.create(organization=self.real_org, name='真实供应商')
        self.real_report = DailyReport.objects.create(
            branch=self.real_branch, date=date(2026, 1, 15), total_revenue=123456, total_customers=42,
        )
        self.real_purchase = PurchaseRecord.objects.create(
            branch=self.real_branch, date=date(2026, 1, 15), supplier=self.real_supplier,
            item_name='真实商品', quantity=1, unit_price=1000, amount=1000,
        )
        self.real_product = Product.objects.create(organization=self.real_org, name='真实产品')


@override_settings(DEBUG=True)
class DemoSeedIsolationTests(RealTenantMixin, TestCase):
    def setUp(self):
        self.create_real_tenant()
        seed(months=1)

    def test_the_demo_tenant_is_created(self):
        self.assertTrue(Organization.objects.filter(code=DEMO_ORG_CODE).exists())
        self.assertEqual(demo_org().branches.count(), 3)

    def test_the_real_tenant_is_completely_untouched(self):
        self.real_report.refresh_from_db()
        self.real_purchase.refresh_from_db()
        self.real_staff.refresh_from_db()
        self.assertEqual(self.real_report.total_revenue, 123456)
        self.assertEqual(self.real_purchase.item_name, '真实商品')
        self.assertEqual(self.real_staff.name, '真实员工')
        self.assertEqual(Organization.objects.get(code='real-customer').name_zh, '真实客户')

    def test_no_demo_row_lands_in_the_real_tenant(self):
        self.assertEqual(DailyReport.objects.filter(branch=self.real_branch).count(), 1)
        self.assertEqual(PurchaseRecord.objects.filter(branch=self.real_branch).count(), 1)
        self.assertEqual(StaffMember.objects.filter(branch=self.real_branch).count(), 1)
        self.assertEqual(Supplier.objects.filter(organization=self.real_org).count(), 1)
        self.assertEqual(Product.objects.filter(organization=self.real_org).count(), 1)

    def test_the_real_admin_account_still_works(self):
        self.real_user.refresh_from_db()
        self.assertTrue(self.real_user.check_password('realpass123'))

    def test_every_demo_object_is_labelled(self):
        # So a leftover row, or a screenshot from a sales call, is
        # identifiable at a glance as not-real.
        for branch in demo_org().branches.all():
            self.assertIn(DEMO_PREFIX, branch.name_ja)
        for member in StaffMember.objects.filter(branch__organization=demo_org()):
            self.assertIn(DEMO_PREFIX, member.name)
        for supplier in Supplier.objects.filter(organization=demo_org()):
            self.assertIn(DEMO_PREFIX, supplier.name)

    def test_demo_accounts_belong_only_to_the_demo_organization(self):
        for user in User.objects.filter(username__startswith='demo-'):
            self.assertEqual(user.organization_id, demo_org().id)


@override_settings(DEBUG=True)
class DemoSeedIdempotencyTests(TestCase):
    def test_running_twice_produces_the_same_row_counts(self):
        seed(months=1)
        counts = self.snapshot()
        seed(months=1)
        self.assertEqual(self.snapshot(), counts)

    def test_running_three_times_still_produces_the_same_counts(self):
        seed(months=1)
        seed(months=1)
        first = self.snapshot()
        seed(months=1)
        self.assertEqual(self.snapshot(), first)

    def test_a_second_run_does_not_duplicate_branches_or_staff(self):
        seed(months=1)
        seed(months=1)
        self.assertEqual(Branch.objects.filter(organization=demo_org()).count(), 3)
        self.assertEqual(
            StaffMember.objects.filter(branch__organization=demo_org(), branch__code='b1').count(), 6,
        )

    def snapshot(self):
        org = demo_org()
        branch_ids = list(org.branches.values_list('id', flat=True))
        return {
            'branches': len(branch_ids),
            'users': User.objects.filter(organization=org).count(),
            'staff': StaffMember.objects.filter(branch_id__in=branch_ids).count(),
            'suppliers': Supplier.objects.filter(organization=org).count(),
            'products': Product.objects.filter(organization=org).count(),
            'reports': DailyReport.objects.filter(branch_id__in=branch_ids).count(),
            'purchases': PurchaseRecord.objects.filter(branch_id__in=branch_ids).count(),
            'shifts': Shift.objects.filter(branch_id__in=branch_ids).count(),
            'attendance': ActualWorkRecord.objects.filter(branch_id__in=branch_ids).count(),
        }


@override_settings(DEBUG=True)
class DemoSeedPurgeTests(RealTenantMixin, TestCase):
    def setUp(self):
        self.create_real_tenant()
        seed(months=1)

    def test_purge_removes_the_demo_tenant_entirely(self):
        seed(purge=True)
        self.assertFalse(Organization.objects.filter(code=DEMO_ORG_CODE).exists())
        self.assertFalse(User.objects.filter(username__startswith='demo-').exists())

    def test_purge_leaves_the_real_tenant_completely_intact(self):
        seed(purge=True)
        self.assertTrue(Organization.objects.filter(code='real-customer').exists())
        self.real_report.refresh_from_db()
        self.assertEqual(self.real_report.total_revenue, 123456)
        self.assertEqual(DailyReport.objects.filter(branch=self.real_branch).count(), 1)
        self.assertEqual(PurchaseRecord.objects.filter(branch=self.real_branch).count(), 1)
        self.assertEqual(Supplier.objects.filter(organization=self.real_org).count(), 1)
        self.assertEqual(Product.objects.filter(organization=self.real_org).count(), 1)
        self.assertEqual(StaffMember.objects.filter(branch=self.real_branch).count(), 1)
        self.assertTrue(User.objects.filter(username='real-admin').exists())

    def test_purge_on_a_clean_database_is_a_no_op_not_an_error(self):
        seed(purge=True)
        output = seed(purge=True)
        self.assertIn('nothing to purge', output)
        self.assertTrue(Organization.objects.filter(code='real-customer').exists())

    def test_seed_purge_seed_round_trips(self):
        seed(purge=True)
        seed(months=1)
        self.assertEqual(demo_org().branches.count(), 3)
        self.assertEqual(DailyReport.objects.filter(branch=self.real_branch).count(), 1)


class DemoSeedGuardTests(TestCase):
    @override_settings(DEBUG=False)
    def test_it_refuses_to_run_on_production_settings_without_confirm(self):
        with self.assertRaises(CommandError) as ctx:
            seed(months=1)
        self.assertIn('--confirm', str(ctx.exception))
        self.assertFalse(Organization.objects.filter(code=DEMO_ORG_CODE).exists())

    @override_settings(DEBUG=False)
    def test_purge_is_also_guarded_outside_debug(self):
        with self.assertRaises(CommandError):
            seed(purge=True)

    @override_settings(DEBUG=False)
    def test_explicit_confirm_allows_it_outside_debug(self):
        seed(months=1, confirm=True)
        self.assertTrue(Organization.objects.filter(code=DEMO_ORG_CODE).exists())


@override_settings(DEBUG=True)
class DemoSeedContentTests(TestCase):
    """The demo has to have something to actually demonstrate."""

    @classmethod
    def setUpTestData(cls):
        seed(months=2)

    def test_there_is_operating_history_across_several_branches(self):
        branch_ids = list(demo_org().branches.values_list('id', flat=True))
        # months=2 spans the previous month plus this month to date.
        self.assertGreater(DailyReport.objects.filter(branch_id__in=branch_ids).count(), 80)
        self.assertGreater(PurchaseRecord.objects.filter(branch_id__in=branch_ids).count(), 20)
        # Every branch has its own reports, not just the first one.
        for branch_id in branch_ids:
            self.assertGreater(DailyReport.objects.filter(branch_id=branch_id).count(), 20)

    def test_revenue_varies_rather_than_being_a_flat_line(self):
        revenues = set(
            DailyReport.objects.filter(branch__organization=demo_org())
            .values_list('total_revenue', flat=True)[:40]
        )
        self.assertGreater(len(revenues), 20, 'demo revenue should look like a real business, not a constant')

    def test_attendance_includes_the_exceptions_a_demo_needs_to_show(self):
        records = ActualWorkRecord.objects.filter(branch__organization=demo_org())
        self.assertTrue(records.filter(absent=True).exists(), 'needs an absence to show')
        self.assertTrue(records.filter(late_minutes__gt=0).exists(), 'needs a late arrival to show')
        self.assertTrue(
            records.filter(actual_end__isnull=True, absent=False).exists(),
            'needs an unfinished day to show',
        )

    def test_there_is_a_pending_correction_for_the_approval_queue(self):
        self.assertTrue(
            AttendanceCorrectionRequest.objects.filter(
                branch__organization=demo_org(),
                status=AttendanceCorrectionRequest.Status.PENDING,
            ).exists(),
        )

    def test_the_demo_logins_can_actually_authenticate(self):
        for username, password in (
            ('demo-admin', 'demo-admin-2026'),
            ('demo-branch', 'demo-branch-2026'),
            ('demo-staff', 'demo-staff-2026'),
        ):
            user = User.objects.get(username=username)
            self.assertTrue(user.check_password(password), username)

    def test_the_demo_is_deterministic_so_a_rehearsed_number_stays_put(self):
        branch = demo_org().branches.get(code='b1')
        before = list(
            DailyReport.objects.filter(branch=branch).order_by('date')
            .values_list('date', 'total_revenue')[:10]
        )
        seed(months=2)
        after = list(
            DailyReport.objects.filter(branch=branch).order_by('date')
            .values_list('date', 'total_revenue')[:10]
        )
        self.assertEqual(before, after)


@override_settings(DEBUG=True)
class DemoSeedStaffAccountTests(TestCase):
    """The staff login has to be usable, not merely creatable.

    `demo-staff` exists to demonstrate the employee-side attendance screen.
    Without a linked StaffMember the account authenticates and then every
    employee attendance call refuses it (AttendanceScopedMixin scopes a
    staff caller by `user.staff_member_id`, and `resolve_employee` rejects
    an unlinked account outright), so the one screen it exists for would be
    empty — the demo would look broken in front of a customer.
    """

    @classmethod
    def setUpTestData(cls):
        seed(months=1)

    def staff_user(self):
        return User.objects.get(username='demo-staff')

    def test_the_staff_login_is_linked_to_an_employee_record(self):
        user = self.staff_user()
        self.assertIsNotNone(user.staff_member_id, 'demo-staff must point at a StaffMember')
        self.assertEqual(user.staff_member.branch_id, user.branch_id)
        self.assertIn(DEMO_PREFIX, user.staff_member.name)

    def test_the_linked_employee_belongs_to_the_demo_tenant(self):
        user = self.staff_user()
        self.assertEqual(user.staff_member.branch.organization_id, demo_org().id)

    def test_the_linked_employee_has_attendance_to_look_at(self):
        user = self.staff_user()
        self.assertTrue(
            ActualWorkRecord.objects.filter(employee_id=user.staff_member_id).exists(),
            'the employee screen would be empty',
        )

    def test_the_employee_attendance_api_accepts_the_demo_staff_account(self):
        """The account check the employee screen actually depends on: both
        the own-records list and the punch-state endpoint, through the real
        JWT login rather than force_authenticate."""
        client = APIClient()
        token = client.post('/api/token/', {'username': 'demo-staff', 'password': 'demo-staff-2026'})
        self.assertEqual(token.status_code, 200, token.content)
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.data["access"]}')

        records = client.get('/api/actual-work-records/')
        self.assertEqual(records.status_code, 200, records.content)
        rows = records.data['results'] if 'results' in records.data else records.data
        self.assertTrue(rows, 'linked staff account should see its own attendance')

        state = client.get('/api/attendance-punches/today/')
        self.assertEqual(state.status_code, 200, state.content)
        self.assertIn('canClockIn', state.data)

    def test_the_link_survives_a_second_run(self):
        first = self.staff_user().staff_member_id
        seed(months=1)
        self.assertEqual(self.staff_user().staff_member_id, first)
        self.assertEqual(
            User.objects.filter(username='demo-staff', staff_member__isnull=False).count(), 1,
        )

    def test_the_admin_and_branch_logins_stay_unlinked(self):
        # Only a staff-role account represents one employee; linking a
        # manager would scope them down to their own rows.
        for username in ('demo-admin', 'demo-branch'):
            self.assertIsNone(User.objects.get(username=username).staff_member_id, username)


class DemoSeedMonthRangeTests(SimpleTestCase):
    """`--months` counts calendar months, including the current one."""

    def test_zero_months_back_is_the_month_itself(self):
        self.assertEqual(months_before(date(2026, 11, 1), 0), date(2026, 11, 1))

    def test_three_months_spans_this_month_and_the_two_before_it(self):
        self.assertEqual(months_before(date(2026, 11, 1), 2), date(2026, 9, 1))

    def test_it_steps_back_across_a_year_boundary(self):
        self.assertEqual(months_before(date(2026, 2, 1), 3), date(2025, 11, 1))
        self.assertEqual(months_before(date(2026, 1, 1), 1), date(2025, 12, 1))

    def test_a_short_february_does_not_shift_the_answer(self):
        """The bug this replaces: 31-day steps from March land in December
        instead of January, so the demo generated one month too few."""
        self.assertEqual(months_before(date(2026, 3, 1), 2), date(2026, 1, 1))
        self.assertEqual(months_before(date(2026, 4, 1), 2), date(2026, 2, 1))
        self.assertEqual(months_before(date(2026, 3, 1), 1), date(2026, 2, 1))

    def test_every_month_of_the_year_steps_back_exactly_two_months(self):
        for month in range(1, 13):
            start = date(2026, month, 1)
            got = months_before(start, 2)
            expected_index = start.year * 12 + (start.month - 1) - 2
            self.assertEqual(got, date(expected_index // 12, expected_index % 12 + 1, 1), start)
            self.assertEqual(got.day, 1)


@override_settings(DEBUG=True)
class DemoSeedMonthCoverageTests(TestCase):
    """The range the seed actually generates, not just the arithmetic."""

    @classmethod
    def setUpTestData(cls):
        seed(months=3)

    def test_the_history_starts_on_the_first_of_the_right_month(self):
        earliest = (
            DailyReport.objects.filter(branch__organization=demo_org())
            .order_by('date').values_list('date', flat=True).first()
        )
        self.assertEqual(earliest, months_before(date.today().replace(day=1), 2))

    def test_three_distinct_months_are_covered(self):
        months = {
            d.replace(day=1)
            for d in DailyReport.objects.filter(branch__organization=demo_org())
            .values_list('date', flat=True)
        }
        self.assertEqual(len(months), 3, sorted(months))
        self.assertIn(date.today().replace(day=1), months)


@override_settings(DEBUG=True)
class DemoSeedScheduleTests(TestCase):
    """The demo schedule has to show a time-based roster, not three slots."""

    @classmethod
    def setUpTestData(cls):
        seed(months=2)

    def demo_branch(self):
        return demo_org().branches.order_by('id').first()

    def test_the_first_branch_gets_its_named_templates(self):
        names = set(ShiftTemplate.objects.filter(branch=self.demo_branch()).values_list('name', flat=True))
        self.assertEqual(names, {'オープン', 'ランチ', '通し', 'ディナー', '深夜'})

    def test_the_schedule_uses_many_time_shapes_including_overnight_and_typed_times(self):
        shifts = Shift.objects.filter(branch=self.demo_branch())
        shapes = set(shifts.values_list('planned_start', 'planned_end'))
        self.assertGreater(len(shapes), 3)
        self.assertTrue(shifts.filter(crosses_midnight=True).exists())
        self.assertTrue(shifts.filter(template__isnull=True).exists(), 'needs a time typed straight into the grid')

    def test_a_rerun_restores_the_palette_and_keeps_every_shifts_times(self):
        branch = self.demo_branch()
        ShiftTemplate.objects.create(branch=branch, name='', start_time='10:30', end_time='15:00')
        before = sorted(Shift.objects.filter(branch=branch).values_list('id', 'planned_start', 'planned_end'))
        seed(months=2)
        self.assertEqual(ShiftTemplate.objects.filter(branch=branch).count(), 5)
        after = sorted(Shift.objects.filter(branch=branch).values_list('id', 'planned_start', 'planned_end'))
        self.assertEqual(before, after)

    def test_no_day_labelled_plan_differs_from_its_shift(self):
        # A 'plan' record is the schedule's own copy; a late day came from
        # punches. Labelling a late day 'plan' would be untrue, and the next
        # schedule save would put it back to the planned times.
        for record in ActualWorkRecord.objects.filter(
            branch=self.demo_branch(), source=ActualWorkRecord.Source.PLAN,
        ).select_related('shift'):
            self.assertEqual(
                (record.actual_start, record.actual_end, record.actual_break_minutes),
                (record.shift.planned_start, record.shift.planned_end, record.shift.planned_break_minutes),
            )
