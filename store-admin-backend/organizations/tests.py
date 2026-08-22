from datetime import date
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.models import User
from common.test_utils import TwoOrganizationApiTestCase
from dailyreports.models import DailyReport
from paymentmethods.models import PaymentMethodDef
from purchasing.models import PurchaseRecord
from scheduling.models import SchedulePeriod
from staff.models import StaffMember
from wages.models import WageRule

from .models import Organization


class ProvisionOrganizationCommandTests(TwoOrganizationApiTestCase):
    def test_provisions_atomic_tenant_admin_and_optional_branch(self):
        call_command(
            'provision_organization', code='company-c', name_zh='C集团', name_ja='Cグループ',
            admin_account='company-c-admin', admin_password='safe-test-password',
            branch_code='first', branch_name_zh='第一店', branch_name_ja='第一店', stdout=StringIO(),
        )
        organization = Organization.objects.get(code='company-c')
        user = User.objects.get(username='company-c-admin')
        self.assertEqual(user.organization, organization)
        self.assertTrue(user.check_password('safe-test-password'))
        self.assertFalse(user.is_superuser)
        self.assertEqual(organization.branches.count(), 1)

    def test_duplicate_global_account_creates_nothing(self):
        before = Organization.objects.count()
        with self.assertRaises(CommandError):
            call_command(
                'provision_organization', code='should-rollback', name_zh='X', name_ja='X',
                admin_account=self.admin_a.username, admin_password='safe-test-password', stdout=StringIO(),
            )
        self.assertEqual(Organization.objects.count(), before)
        self.assertFalse(Organization.objects.filter(code='should-rollback').exists())


class OrganizationIsolationTests(TwoOrganizationApiTestCase):
    """Section 3.5's checklist, executed against the real running API —
    every one of these is a genuine cross-tenant data leak if it fails."""

    def test_admin_cannot_forge_other_organization_branch_on_create(self):
        self.login_as(self.admin_a)
        before = DailyReport.objects.count()
        response = self.client.post('/api/daily-reports/', {
            'branch': self.branch_b1.id, 'date': '2026-08-19', 'total_revenue': 1000,
        }, format='json')
        self.assertIn(response.status_code, (400, 403, 404))
        self.assertEqual(DailyReport.objects.count(), before)

    def test_branch_cannot_reference_other_organization_supplier(self):
        self.login_as(self.branch_a1_user)
        before = PurchaseRecord.objects.count()
        response = self.client.post('/api/purchases/', {
            'supplier': self.supplier_b.id, 'date': '2026-08-19',
            'item_name': '攻击数据', 'quantity': 1, 'unit_price': 100,
        }, format='json')
        self.assertIn(response.status_code, (400, 403, 404))
        self.assertEqual(PurchaseRecord.objects.count(), before)

    def test_admin_cannot_create_payment_method_in_other_organization(self):
        self.login_as(self.admin_a)
        response = self.client.post('/api/payment-methods/', {
            'branch': self.branch_b1.id, 'code': 'forged', 'custom_name': 'forged',
        }, format='json')
        self.assertIn(response.status_code, (400, 403, 404))
        self.assertFalse(PaymentMethodDef.objects.filter(branch=self.branch_b1, code='forged').exists())

    def test_admin_a_branch_list_excludes_org_b(self):
        self.login_as(self.admin_a)
        resp = self.client.get('/api/branches/')
        ids = {row['id'] for row in resp.data}
        self.assertEqual(ids, {self.branch_a1.id, self.branch_a2.id})

    def test_admin_a_cannot_read_org_b_branch_by_id(self):
        self.login_as(self.admin_a)
        resp = self.client.get(f'/api/branches/{self.branch_b1.id}/')
        self.assertEqual(resp.status_code, 404)

    def test_admin_a_cannot_modify_org_b_branch_by_known_id(self):
        self.login_as(self.admin_a)
        resp = self.client.patch(f'/api/branches/{self.branch_b1.id}/', {'name_zh': '改名'}, format='json')
        self.assertEqual(resp.status_code, 404)
        resp = self.client.delete(f'/api/branches/{self.branch_b1.id}/')
        self.assertEqual(resp.status_code, 404)
        self.branch_b1.refresh_from_db()
        self.assertEqual(self.branch_b1.name_zh, 'B集团1号店')

    def test_admin_a_account_list_excludes_org_b(self):
        self.login_as(self.admin_a)
        resp = self.client.get('/api/users/')
        usernames = {row['account'] for row in resp.data}
        self.assertNotIn('org-b-admin', usernames)
        self.assertNotIn('org-b-branch1-user', usernames)

    def test_admin_a_cannot_reset_org_b_account_password_by_known_id(self):
        self.login_as(self.admin_a)
        resp = self.client.post(f'/api/users/{self.branch_b1_user.id}/reset_password/', {
            'password': 'hijacked123',
        }, format='json')
        self.assertEqual(resp.status_code, 404)

    def test_admin_a_staff_list_excludes_org_b(self):
        self.login_as(self.admin_a)
        resp = self.client.get('/api/staff/')
        ids = {row['id'] for row in resp.data}
        self.assertEqual(ids, {self.staff_a1.id})
        self.assertNotIn(self.staff_b1.id, ids)

    def test_admin_a_cannot_edit_org_b_staff_by_known_id(self):
        self.login_as(self.admin_a)
        resp = self.client.patch(f'/api/staff/{self.staff_b1.id}/', {'name': '改名'}, format='json')
        self.assertEqual(resp.status_code, 404)

    def test_admin_a_supplier_list_excludes_org_b(self):
        self.login_as(self.admin_a)
        resp = self.client.get('/api/suppliers/')
        ids = {row['id'] for row in resp.data}
        self.assertEqual(ids, {self.supplier_a.id})

    def test_admin_a_cannot_read_org_b_supplier_by_known_id(self):
        self.login_as(self.admin_a)
        resp = self.client.get(f'/api/suppliers/{self.supplier_b.id}/')
        self.assertEqual(resp.status_code, 404)

    def test_admin_a_cannot_see_org_b_daily_reports_or_purchases(self):
        DailyReport.objects.create(
            branch=self.branch_b1, date=date(2026, 5, 1), total_revenue=99999, total_customers=10,
        )
        PurchaseRecord.objects.create(
            branch=self.branch_b1, date=date(2026, 5, 1), supplier=self.supplier_b,
            item_name='B集团机密商品', quantity=1, unit_price=1,
        )
        self.login_as(self.admin_a)
        resp = self.client.get('/api/daily-reports/')
        self.assertEqual(resp.data, [])
        resp = self.client.get('/api/purchases/')
        self.assertEqual(resp.data['results'], [])

    def test_admin_a_cannot_see_org_b_scheduling_or_wages(self):
        SchedulePeriod.objects.create(branch=self.branch_b1, start_date=date(2026, 5, 4), end_date=date(2026, 5, 10))
        WageRule.objects.create(employee=self.staff_b1, effective_from=date(2026, 5, 1), hourly_rate=1000)
        self.login_as(self.admin_a)
        resp = self.client.get('/api/schedule-periods/')
        self.assertEqual(resp.data, [])
        resp = self.client.get('/api/wage-rules/')
        self.assertEqual(resp.data, [])

    def test_admin_a_cannot_create_wage_rule_for_org_b_employee(self):
        self.login_as(self.admin_a)
        resp = self.client.post('/api/wage-rules/', {
            'employee': self.staff_b1.id, 'effective_from': '2026-05-01', 'hourly_rate': 1000,
        }, format='json')
        # employee field is validated against a global StaffMember queryset,
        # so this either 400s (not found) or 403s (branch-scope check) —
        # either way it must never create a rule against another Organization.
        self.assertIn(resp.status_code, (400, 403))
        self.assertFalse(WageRule.objects.filter(employee=self.staff_b1).exists())

    def test_branch_a1_account_cannot_see_branch_a2_daily_reports(self):
        DailyReport.objects.create(
            branch=self.branch_a2, date=date(2026, 5, 1), total_revenue=50000, total_customers=20,
        )
        self.login_as(self.branch_a1_user)
        resp = self.client.get('/api/daily-reports/')
        self.assertEqual(resp.data, [])

    def test_branch_a1_account_cannot_see_branch_a2_purchases(self):
        PurchaseRecord.objects.create(
            branch=self.branch_a2, date=date(2026, 5, 1), supplier=self.supplier_a,
            item_name='A2店专用', quantity=1, unit_price=1,
        )
        self.login_as(self.branch_a1_user)
        resp = self.client.get('/api/purchases/')
        self.assertEqual(resp.data['results'], [])

    def test_staff_only_ever_sees_its_own_data(self):
        other_staff = StaffMember.objects.create(
            name='A集团另一员工', branch=self.branch_a1, employment_type=StaffMember.EmploymentType.HOURLY,
        )
        self.login_as(self.staff_user_a1)
        resp = self.client.get('/api/availability-requests/')
        self.assertEqual(resp.status_code, 200)  # reachable (self-service opt-out), but scoped
        resp = self.client.get(f'/api/wage-employee-results/?employee={other_staff.id}')
        self.assertEqual(resp.data, [])

    def test_dashboard_summary_never_mixes_organizations(self):
        DailyReport.objects.create(
            branch=self.branch_b1, date=date.today(), total_revenue=888888, total_customers=1,
        )
        self.login_as(self.admin_a)
        resp = self.client.get('/api/dashboard/summary/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(888888, [row.get('revenue') for row in resp.data.get('branchRevenueToday', [])])

    def test_monthly_analysis_admin_a_all_branches_excludes_org_b(self):
        DailyReport.objects.create(
            branch=self.branch_a1, date=date(2026, 6, 5), total_revenue=10000, total_customers=5,
        )
        DailyReport.objects.create(
            branch=self.branch_b1, date=date(2026, 6, 5), total_revenue=777777, total_customers=1,
        )
        self.login_as(self.admin_a)
        resp = self.client.get('/api/dashboard/monthly-analysis/?month=2026-06')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['revenue'], '10000')
        branch_ids_in_comparison = {row['branchId'] for row in resp.data['branchComparison']}
        self.assertNotIn(self.branch_b1.id, branch_ids_in_comparison)

    def test_monthly_analysis_admin_a_cannot_target_org_b_branch_by_param(self):
        self.login_as(self.admin_a)
        resp = self.client.get(f'/api/dashboard/monthly-analysis/?month=2026-06&branch={self.branch_b1.id}')
        self.assertEqual(resp.status_code, 400)

    def test_monthly_analysis_staff_still_403(self):
        self.login_as(self.staff_user_a1)
        resp = self.client.get('/api/dashboard/monthly-analysis/?month=2026-06')
        self.assertEqual(resp.status_code, 403)

    def test_payment_methods_never_cross_organization(self):
        self.login_as(self.admin_a)
        resp = self.client.get(f'/api/payment-methods/?branch={self.branch_a1.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(len(resp.data) > 0)
        resp = self.client.get(f'/api/payment-methods/?branch={self.branch_b1.id}')
        self.assertEqual(resp.data, [])

    def test_purchase_price_history_never_crosses_organization(self):
        PurchaseRecord.objects.create(
            branch=self.branch_a1, date=date(2026, 5, 1), supplier=self.supplier_a,
            item_name='空心菜', quantity=1, unit_price=100,
        )
        PurchaseRecord.objects.create(
            branch=self.branch_b1, date=date(2026, 5, 1), supplier=self.supplier_b,
            item_name='空心菜', quantity=1, unit_price=999,
        )
        self.login_as(self.admin_a)
        resp = self.client.get('/api/purchases/suggestions/', {'supplier': self.supplier_a.id, 'q': '空心菜'})
        self.assertEqual(resp.status_code, 200)
        for row in resp.data:
            self.assertNotEqual(row.get('lastUnitPrice'), 999)
