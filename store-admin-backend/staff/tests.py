from datetime import date

from common.test_utils import ApiTestCase, TwoOrganizationApiTestCase
from staff.models import StaffMember, StaffTransfer


class StaffWorkAreaAndWageSettingTests(ApiTestCase):
    def test_branch_can_set_work_area_and_create_current_wage_setting(self):
        self.login_as(self.branch_a_user)
        response = self.client.patch(f'/api/staff/{self.staff_employee.id}/', {
            'work_area': 'kitchen',
            'wage_setting': {
                'hourly_rate': 1200, 'transportation_amount': 800,
                'effective_from': '2026-08-01', 'note': 'current setting',
            },
        }, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.staff_employee.refresh_from_db()
        self.assertEqual(self.staff_employee.work_area, 'kitchen')
        rule = self.staff_employee.wage_rules.get()
        self.assertEqual(rule.hourly_rate, 1200)
        self.assertEqual(rule.transportation_amount, 800)

    def test_new_setting_closes_old_rule_day_before(self):
        from wages.models import WageRule
        old = WageRule.objects.create(
            employee=self.staff_employee, effective_from=date(2026, 1, 1), hourly_rate=1000,
        )
        self.login_as(self.branch_a_user)
        response = self.client.patch(f'/api/staff/{self.staff_employee.id}/', {
            'wage_setting': {
                'hourly_rate': 1300, 'transportation_amount': 900,
                'effective_from': '2026-08-01', 'note': '',
            },
        }, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        old.refresh_from_db()
        self.assertEqual(old.effective_to, date(2026, 7, 31))


class StaffMemberPermissionBoundaryTests(ApiTestCase):
    """branch accounts must only read/write employees at their own branch,
    never be able to set/change `branch` to move an employee elsewhere
    (even via a forged direct request), and staff must never reach this
    endpoint at all."""

    def setUp(self):
        super().setUp()
        self.employee_b = StaffMember.objects.create(name='测试分店B员工', branch=self.branch_b)

    def test_branch_account_only_lists_its_own_employees(self):
        self.login_as(self.branch_a_user)
        resp = self.client.get('/api/staff/')
        self.assertEqual(resp.status_code, 200)
        ids = {row['id'] for row in resp.data}
        self.assertEqual(ids, {self.staff_employee.id})

    def test_branch_account_cannot_read_another_branch_employee(self):
        self.login_as(self.branch_a_user)
        resp = self.client.get(f'/api/staff/{self.employee_b.id}/')
        self.assertEqual(resp.status_code, 404)

    def test_branch_account_create_auto_binds_own_branch(self):
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/staff/', {
            'name': '新员工', 'branch': self.branch_b.id, 'role': '', 'phone': '',
            'status': 'active', 'employment_type': 'regular_monthly',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        created = StaffMember.objects.get(id=resp.data['id'])
        self.assertEqual(created.branch_id, self.branch_a.id)

    def test_branch_account_cannot_forge_branch_on_update(self):
        self.login_as(self.branch_a_user)
        resp = self.client.patch(f'/api/staff/{self.staff_employee.id}/', {
            'branch': self.branch_b.id,
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.staff_employee.refresh_from_db()
        self.assertEqual(self.staff_employee.branch_id, self.branch_a.id)

    def test_branch_account_cannot_edit_another_branch_employee(self):
        self.login_as(self.branch_a_user)
        resp = self.client.patch(f'/api/staff/{self.employee_b.id}/', {'name': '改名'}, format='json')
        self.assertEqual(resp.status_code, 404)

    def test_admin_branch_also_never_moves_on_normal_update(self):
        self.login_as(self.admin)
        resp = self.client.patch(f'/api/staff/{self.staff_employee.id}/', {
            'branch': self.branch_b.id,
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.staff_employee.refresh_from_db()
        self.assertEqual(self.staff_employee.branch_id, self.branch_a.id)

    def test_admin_sees_all_employees(self):
        self.login_as(self.admin)
        resp = self.client.get('/api/staff/')
        self.assertEqual(resp.status_code, 200)
        ids = {row['id'] for row in resp.data}
        self.assertEqual(ids, {self.staff_employee.id, self.employee_b.id})

    def test_staff_account_blocked_entirely(self):
        self.login_as(self.staff_user)
        resp = self.client.get('/api/staff/')
        self.assertEqual(resp.status_code, 403)


class StaffTransferTests(TwoOrganizationApiTestCase):
    """Employee transfers: admin-only, same-Organization-only, updates the
    employee's current branch (and its linked login account's branch, if
    any), warns instead of silently dropping future shifts at the old
    branch, and is an append-only audit log."""

    def test_branch_account_cannot_create_transfer(self):
        self.login_as(self.branch_a1_user)
        resp = self.client.post('/api/staff-transfers/', {
            'employee': self.staff_a1.id, 'to_branch': self.branch_a2.id, 'effective_date': '2026-06-01',
        }, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_staff_account_cannot_create_transfer(self):
        self.login_as(self.staff_user_a1)
        resp = self.client.post('/api/staff-transfers/', {
            'employee': self.staff_a1.id, 'to_branch': self.branch_a2.id, 'effective_date': '2026-06-01',
        }, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_admin_cannot_transfer_to_another_organizations_branch(self):
        self.login_as(self.admin_a)
        resp = self.client.post('/api/staff-transfers/', {
            'employee': self.staff_a1.id, 'to_branch': self.branch_b1.id, 'effective_date': '2026-06-01',
        }, format='json')
        self.assertEqual(resp.status_code, 403)
        self.staff_a1.refresh_from_db()
        self.assertEqual(self.staff_a1.branch_id, self.branch_a1.id)

    def test_admin_cannot_transfer_org_b_employee(self):
        self.login_as(self.admin_a)
        resp = self.client.post('/api/staff-transfers/', {
            'employee': self.staff_b1.id, 'to_branch': self.branch_a1.id, 'effective_date': '2026-06-01',
        }, format='json')
        self.assertIn(resp.status_code, (400, 403))

    def test_same_branch_transfer_rejected(self):
        self.login_as(self.admin_a)
        resp = self.client.post('/api/staff-transfers/', {
            'employee': self.staff_a1.id, 'to_branch': self.branch_a1.id, 'effective_date': '2026-06-01',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_successful_transfer_updates_employee_branch_and_creates_record(self):
        self.login_as(self.admin_a)
        resp = self.client.post('/api/staff-transfers/', {
            'employee': self.staff_a1.id, 'to_branch': self.branch_a2.id,
            'effective_date': '2026-06-01', 'reason': '业务调整',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.staff_a1.refresh_from_db()
        self.assertEqual(self.staff_a1.branch_id, self.branch_a2.id)
        self.assertEqual(StaffTransfer.objects.filter(employee=self.staff_a1).count(), 1)
        record = StaffTransfer.objects.get(employee=self.staff_a1)
        self.assertEqual(record.from_branch_id, self.branch_a1.id)
        self.assertEqual(record.to_branch_id, self.branch_a2.id)
        self.assertEqual(record.changed_by_id, self.admin_a.id)

    def test_transfer_syncs_linked_login_account_branch(self):
        self.login_as(self.admin_a)
        resp = self.client.post('/api/staff-transfers/', {
            'employee': self.staff_a1.id, 'to_branch': self.branch_a2.id, 'effective_date': '2026-06-01',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.staff_user_a1.refresh_from_db()
        self.assertEqual(self.staff_user_a1.branch_id, self.branch_a2.id)

    def test_historical_records_keep_original_branch_after_transfer(self):
        from dailyreports.models import DailyReport
        from scheduling.models import ActualWorkRecord

        record = ActualWorkRecord.objects.create(
            branch=self.branch_a1, employee=self.staff_a1, work_date=date(2026, 5, 1),
            actual_start='09:00', actual_end='17:00', status=ActualWorkRecord.Status.MANAGER_CONFIRMED,
        )
        report = DailyReport.objects.create(
            branch=self.branch_a1, date=date(2026, 5, 1), person_in_charge=self.staff_a1,
            total_revenue=10000, total_customers=5,
        )
        self.login_as(self.admin_a)
        resp = self.client.post('/api/staff-transfers/', {
            'employee': self.staff_a1.id, 'to_branch': self.branch_a2.id, 'effective_date': '2026-06-01',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)

        record.refresh_from_db()
        report.refresh_from_db()
        self.assertEqual(record.branch_id, self.branch_a1.id)
        self.assertEqual(report.branch_id, self.branch_a1.id)

    def test_future_shift_at_old_branch_warns_without_force(self):
        from scheduling.models import SchedulePeriod, Shift

        period = SchedulePeriod.objects.create(
            branch=self.branch_a1, start_date=date(2026, 6, 1), end_date=date(2026, 6, 7),
        )
        Shift.objects.create(
            period=period, branch=self.branch_a1, employee=self.staff_a1, work_date=date(2026, 6, 3),
            planned_start='09:00', planned_end='17:00',
        )
        self.login_as(self.admin_a)
        resp = self.client.post('/api/staff-transfers/', {
            'employee': self.staff_a1.id, 'to_branch': self.branch_a2.id, 'effective_date': '2026-06-01',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['code'], 'has-future-shifts-at-old-branch')
        self.assertEqual(len(resp.data['shifts']), 1)
        self.staff_a1.refresh_from_db()
        self.assertEqual(self.staff_a1.branch_id, self.branch_a1.id)  # not moved yet

    def test_force_transfer_proceeds_and_does_not_delete_old_shift(self):
        from scheduling.models import SchedulePeriod, Shift

        period = SchedulePeriod.objects.create(
            branch=self.branch_a1, start_date=date(2026, 6, 1), end_date=date(2026, 6, 7),
        )
        shift = Shift.objects.create(
            period=period, branch=self.branch_a1, employee=self.staff_a1, work_date=date(2026, 6, 3),
            planned_start='09:00', planned_end='17:00',
        )
        self.login_as(self.admin_a)
        resp = self.client.post('/api/staff-transfers/', {
            'employee': self.staff_a1.id, 'to_branch': self.branch_a2.id,
            'effective_date': '2026-06-01', 'force': True,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.staff_a1.refresh_from_db()
        self.assertEqual(self.staff_a1.branch_id, self.branch_a2.id)
        self.assertTrue(Shift.objects.filter(id=shift.id).exists())  # not silently deleted

    def test_returning_to_original_branch_creates_new_record_not_overwrite(self):
        self.login_as(self.admin_a)
        self.client.post('/api/staff-transfers/', {
            'employee': self.staff_a1.id, 'to_branch': self.branch_a2.id, 'effective_date': '2026-06-01',
        }, format='json')
        resp = self.client.post('/api/staff-transfers/', {
            'employee': self.staff_a1.id, 'to_branch': self.branch_a1.id, 'effective_date': '2026-07-01',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(StaffTransfer.objects.filter(employee=self.staff_a1).count(), 2)
        self.staff_a1.refresh_from_db()
        self.assertEqual(self.staff_a1.branch_id, self.branch_a1.id)

    def test_transfer_records_are_not_editable_or_deletable(self):
        self.login_as(self.admin_a)
        resp = self.client.post('/api/staff-transfers/', {
            'employee': self.staff_a1.id, 'to_branch': self.branch_a2.id, 'effective_date': '2026-06-01',
        }, format='json')
        transfer_id = resp.data['id']
        resp = self.client.patch(f'/api/staff-transfers/{transfer_id}/', {'reason': '改写历史'}, format='json')
        self.assertEqual(resp.status_code, 405)
        resp = self.client.delete(f'/api/staff-transfers/{transfer_id}/')
        self.assertEqual(resp.status_code, 405)

    def test_admin_a_transfer_list_excludes_org_b(self):
        self.login_as(self.admin_a)
        self.client.post('/api/staff-transfers/', {
            'employee': self.staff_a1.id, 'to_branch': self.branch_a2.id, 'effective_date': '2026-06-01',
        }, format='json')
        self.login_as(self.admin_b)
        resp = self.client.get('/api/staff-transfers/')
        self.assertEqual(resp.data, [])
