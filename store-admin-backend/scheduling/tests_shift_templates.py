"""Time-based scheduling: shift templates, the 0011 slot migration, and
keeping generated attendance records in step with the shifts they copy."""
from datetime import date, time

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from branches.models import Branch
from common.test_utils import ApiTestCase, TwoOrganizationApiTestCase
from organizations.models import Organization
from staff.models import StaffMember

from . import attendance
from .models import (
    ActualWorkRecord, AttendanceChangeLog, AttendancePunch, SchedulePeriod, Shift, ShiftTemplate,
)


def rows(resp):
    return resp.data['results'] if isinstance(resp.data, dict) and 'results' in resp.data else resp.data


class ShiftTemplateApiTests(ApiTestCase):
    def test_admin_creates_a_template_for_a_branch(self):
        self.login_as(self.admin)
        resp = self.client.post('/api/shift-templates/', {
            'branch': self.branch_a.id, 'name': 'ランチ', 'start_time': '11:00', 'end_time': '15:30',
            'break_minutes': 0, 'color': 'blue',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertFalse(resp.data['crosses_midnight'])

    def test_end_not_after_start_means_the_template_runs_past_midnight(self):
        self.login_as(self.admin)
        resp = self.client.post('/api/shift-templates/', {
            'branch': self.branch_a.id, 'name': '深夜', 'start_time': '22:00', 'end_time': '02:00',
            'break_minutes': 30,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertTrue(resp.data['crosses_midnight'])

    def test_same_start_and_end_is_rejected(self):
        self.login_as(self.admin)
        resp = self.client.post('/api/shift-templates/', {
            'branch': self.branch_a.id, 'start_time': '10:00', 'end_time': '10:00',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_break_as_long_as_the_shift_is_rejected(self):
        self.login_as(self.admin)
        resp = self.client.post('/api/shift-templates/', {
            'branch': self.branch_a.id, 'start_time': '10:00', 'end_time': '12:00', 'break_minutes': 120,
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_branch_account_creates_for_its_own_branch_even_if_it_names_another(self):
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/shift-templates/', {
            'branch': self.branch_b.id, 'start_time': '09:00', 'end_time': '13:00',
        }, format='json')
        self.assertEqual(resp.status_code, 403)
        resp = self.client.post('/api/shift-templates/', {
            'start_time': '09:00', 'end_time': '13:00',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(ShiftTemplate.objects.get().branch_id, self.branch_a.id)

    def test_branch_account_never_sees_another_branchs_templates(self):
        other = ShiftTemplate.objects.create(branch=self.branch_b, start_time=time(9), end_time=time(13))
        self.login_as(self.branch_a_user)
        self.assertEqual(rows(self.client.get('/api/shift-templates/')), [])
        self.assertEqual(self.client.patch(
            f'/api/shift-templates/{other.id}/', {'name': 'x'}, format='json').status_code, 404)
        self.assertEqual(self.client.delete(f'/api/shift-templates/{other.id}/').status_code, 404)

    def test_branch_cannot_be_moved_after_creation(self):
        template = ShiftTemplate.objects.create(branch=self.branch_a, start_time=time(9), end_time=time(13))
        self.login_as(self.admin)
        resp = self.client.patch(
            f'/api/shift-templates/{template.id}/', {'branch': self.branch_b.id}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_staff_has_no_access(self):
        self.login_as(self.staff_user)
        self.assertEqual(self.client.get('/api/shift-templates/').status_code, 403)

    def test_deleting_a_template_keeps_the_shifts_times(self):
        template = ShiftTemplate.objects.create(branch=self.branch_a, start_time=time(9), end_time=time(13))
        period = SchedulePeriod.objects.create(
            branch=self.branch_a, month=date(2026, 3, 1), start_date=date(2026, 3, 1), end_date=date(2026, 3, 31),
        )
        shift = Shift.objects.create(
            period=period, branch=self.branch_a, employee=self.staff_employee, work_date=date(2026, 3, 2),
            planned_start=time(9), planned_end=time(13), template=template,
        )
        self.login_as(self.branch_a_user)
        self.assertEqual(self.client.delete(f'/api/shift-templates/{template.id}/').status_code, 204)
        shift.refresh_from_db()
        self.assertIsNone(shift.template_id)
        self.assertEqual((shift.planned_start, shift.planned_end), (time(9), time(13)))


class ShiftTemplateTenantTests(TwoOrganizationApiTestCase):
    def test_admin_cannot_create_or_see_another_organizations_templates(self):
        ShiftTemplate.objects.create(branch=self.branch_b1, start_time=time(9), end_time=time(13))
        self.login_as(self.admin_a)
        self.assertEqual(rows(self.client.get('/api/shift-templates/')), [])
        resp = self.client.post('/api/shift-templates/', {
            'branch': self.branch_b1.id, 'start_time': '09:00', 'end_time': '13:00',
        }, format='json')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(ShiftTemplate.objects.filter(branch=self.branch_b1).count(), 1)


class ShiftTemplateOnShiftTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.period = SchedulePeriod.objects.create(
            branch=self.branch_a, month=date(2026, 3, 1), start_date=date(2026, 3, 1), end_date=date(2026, 3, 31),
        )

    def test_a_shift_cannot_use_another_branchs_template(self):
        foreign = ShiftTemplate.objects.create(branch=self.branch_b, start_time=time(9), end_time=time(13))
        self.login_as(self.admin)
        resp = self.client.post('/api/shifts/', {
            'period': self.period.id, 'branch': self.branch_a.id, 'employee': self.staff_employee.id,
            'work_date': '2026-03-02', 'planned_start': '09:00', 'planned_end': '13:00', 'template': foreign.id,
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('shift-template-branch-mismatch', str(resp.data))

    def test_any_time_can_be_scheduled_without_a_template(self):
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/shifts/', {
            'period': self.period.id, 'branch': self.branch_a.id, 'employee': self.staff_employee.id,
            'work_date': '2026-03-02', 'planned_start': '12:15', 'planned_end': '16:45',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertIsNone(resp.data['template'])


class PlanRecordFollowsShiftTests(ApiTestCase):
    """A generated (source=PLAN) record is the plan's copy, so it has to
    follow the plan — otherwise a retimed or deleted shift keeps being paid
    at its old times."""

    def setUp(self):
        super().setUp()
        self.period = SchedulePeriod.objects.create(
            branch=self.branch_a, month=date(2026, 3, 1), start_date=date(2026, 3, 1), end_date=date(2026, 3, 31),
        )
        self.shift = Shift.objects.create(
            period=self.period, branch=self.branch_a, employee=self.staff_employee, work_date=date(2026, 3, 2),
            planned_start=time(10), planned_end=time(15),
        )
        self.login_as(self.branch_a_user)
        self.client.post(f'/api/schedule-periods/{self.period.id}/generate_actual_records/')
        self.record = ActualWorkRecord.objects.get(employee=self.staff_employee, work_date=date(2026, 3, 2))

    def retime(self, start, end):
        return self.client.patch(f'/api/shifts/{self.shift.id}/', {
            'planned_start': start, 'planned_end': end,
        }, format='json')

    def test_retiming_a_shift_retimes_its_generated_record_and_logs_it(self):
        self.assertEqual(self.retime('12:00', '18:00').status_code, 200)
        self.record.refresh_from_db()
        self.assertEqual((self.record.actual_start, self.record.actual_end), (time(12), time(18)))
        self.assertEqual(self.record.source, ActualWorkRecord.Source.PLAN)
        entry = AttendanceChangeLog.objects.filter(record=self.record, reason='shift_retimed').get()
        self.assertEqual(entry.source, AttendanceChangeLog.Source.GENERATED)
        self.assertEqual(entry.before['actual_start'], '10:00:00')

    def test_a_record_a_manager_edited_is_left_alone(self):
        ActualWorkRecord.objects.filter(pk=self.record.pk).update(
            source=ActualWorkRecord.Source.MANUAL, actual_end=time(16), adjustment_reason='stayed late',
        )
        self.retime('12:00', '18:00')
        self.record.refresh_from_db()
        self.assertEqual((self.record.actual_start, self.record.actual_end), (time(10), time(16)))

    def test_a_locked_record_is_left_alone(self):
        ActualWorkRecord.objects.filter(pk=self.record.pk).update(status=ActualWorkRecord.Status.ADMIN_LOCKED)
        self.retime('12:00', '18:00')
        self.record.refresh_from_db()
        self.assertEqual(self.record.actual_start, time(10))

    def test_deleting_a_shift_removes_its_generated_record(self):
        self.assertEqual(self.client.delete(f'/api/shifts/{self.shift.id}/').status_code, 204)
        self.assertFalse(ActualWorkRecord.objects.filter(pk=self.record.pk).exists())
        entry = AttendanceChangeLog.objects.get(reason='shift_deleted')
        self.assertIsNone(entry.record_id)
        self.assertEqual(entry.employee_id, self.staff_employee.id)

    def test_deleting_a_shift_keeps_a_day_that_was_punched(self):
        ActualWorkRecord.objects.filter(pk=self.record.pk).update(source=ActualWorkRecord.Source.PUNCH)
        self.client.delete(f'/api/shifts/{self.shift.id}/')
        self.record.refresh_from_db()
        self.assertIsNone(self.record.shift_id)

    def test_generate_brings_a_stale_plan_copy_back_in_line(self):
        # A shift retimed before this release, so its record is stale.
        Shift.objects.filter(pk=self.shift.pk).update(planned_start=time(11), planned_end=time(16))
        resp = self.client.post(f'/api/schedule-periods/{self.period.id}/generate_actual_records/')
        self.assertEqual(resp.data['updated'], 1)
        self.record.refresh_from_db()
        self.assertEqual(self.record.actual_start, time(11))

    def test_punches_replace_the_plan_copy_and_await_confirmation(self):
        punched_at = timezone.make_aware(timezone.datetime(2026, 3, 2, 10, 25))
        AttendancePunch.objects.create(
            employee=self.staff_employee, branch=self.branch_a, work_date=date(2026, 3, 2),
            kind=AttendancePunch.Kind.CLOCK_IN, punched_at=punched_at,
        )
        _, applied, _problems = attendance.rebuild_from_punches(
            self.staff_employee, self.branch_a, date(2026, 3, 2),
        )
        self.assertTrue(applied)
        self.record.refresh_from_db()
        self.assertEqual(self.record.source, ActualWorkRecord.Source.PUNCH)
        self.assertEqual(self.record.status, ActualWorkRecord.Status.PENDING)
        self.assertEqual(self.record.actual_start, time(10, 25))
        self.assertIsNone(self.record.actual_end)  # still clocked in

    def test_record_api_reports_planned_and_worked_minutes_as_wages_count_them(self):
        Shift.objects.filter(pk=self.shift.pk).update(planned_break_minutes=30)
        ActualWorkRecord.objects.filter(pk=self.record.pk).update(
            actual_end=time(16), actual_break_minutes=30, source=ActualWorkRecord.Source.MANUAL,
        )
        data = rows(self.client.get('/api/actual-work-records/', {'employee': self.staff_employee.id}))[0]
        self.assertEqual(data['planned_minutes'], 270)   # 10:00-15:00 minus 30
        self.assertEqual(data['worked_minutes'], 330)    # 10:00-16:00 minus 30


class FixedSlotMigrationTests(TransactionTestCase):
    """0011 against real historical state: migrate back to 0010 (where the
    three fixed slots still exist), seed, migrate forward, check."""

    before = [('scheduling', '0010_shifttemplate_shift_template')]
    after = [('scheduling', '0011_shift_templates_from_fixed_slots')]

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(target)
        return executor.loader.project_state(target).apps

    def test_each_branchs_three_slots_become_templates_and_matching_shifts_link(self):
        # Only scheduling is rolled back; the other apps' tables are at
        # their current schema, so their rows are made with the live models.
        org = Organization.objects.create(code='mig-org', name_zh='m', name_ja='m')
        branch = Branch.objects.create(id='mig-branch', organization=org, code='mig', name_zh='m', name_ja='m')
        member = StaffMember.objects.create(name='m', branch=branch)

        apps = self.migrate(self.before)
        Setting = apps.get_model('scheduling', 'BranchScheduleSetting')
        Period = apps.get_model('scheduling', 'SchedulePeriod')
        HistoricalShift = apps.get_model('scheduling', 'Shift')

        Setting.objects.create(branch_id=branch.id, morning_start=time(9, 30), morning_end=time(14, 0))
        period = Period.objects.create(branch_id=branch.id, start_date=date(2026, 3, 1), end_date=date(2026, 3, 31))
        on_slot = HistoricalShift.objects.create(
            period=period, branch_id=branch.id, employee_id=member.id, work_date=date(2026, 3, 2),
            planned_start=time(9, 30), planned_end=time(14, 0),
        )
        custom = HistoricalShift.objects.create(
            period=period, branch_id=branch.id, employee_id=member.id, work_date=date(2026, 3, 3),
            planned_start=time(12, 0), planned_end=time(16, 0),
        )

        apps = self.migrate(self.after)
        Template = apps.get_model('scheduling', 'ShiftTemplate')
        HistoricalShift = apps.get_model('scheduling', 'Shift')
        templates = list(Template.objects.filter(branch_id='mig-branch').order_by('sort_order'))
        self.assertEqual(
            [(t.start_time, t.end_time, t.break_minutes) for t in templates],
            [(time(9, 30), time(14, 0), 0), (time(17, 0), time(22, 0), 0), (time(10, 30), time(22, 0), 120)],
        )
        self.assertEqual(HistoricalShift.objects.get(pk=on_slot.pk).template_id, templates[0].pk)
        unchanged = HistoricalShift.objects.get(pk=custom.pk)
        self.assertIsNone(unchanged.template_id)
        self.assertEqual((unchanged.planned_start, unchanged.planned_end), (time(12, 0), time(16, 0)))
