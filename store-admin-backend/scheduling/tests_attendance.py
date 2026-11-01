"""Tests for the clock-punch attendance layer.

Grouped by the thing being protected rather than by endpoint, because the
risk here is not "does the API return 200" — it is that attendance feeds
payroll, so the tests that matter are the ones pinning:

  * a punch never confirms attendance (PayrollSafetyTests)
  * an employee can only ever act on their own data, and a branch only
    within its own tenant (AttendancePermissionTests,
    AttendanceTenantIsolationTests)
  * an overnight shift lands on one business day (BusinessDateTests)
  * every change leaves a trail (AttendanceChangeLogTests)
"""
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from common.test_utils import ApiTestCase, TwoOrganizationApiTestCase
from staff.models import StaffMember

from . import attendance
from .models import (
    ActualWorkRecord, AttendanceChangeLog, AttendanceCorrectionRequest, AttendancePunch,
    BranchScheduleSetting, SchedulePeriod, Shift,
)


def aware(year, month, day, hour, minute=0):
    """A JST-local datetime as an aware value in the project timezone —
    these tests are about business days in Osaka, so building naive UTC
    datetimes would quietly test the wrong thing."""
    return timezone.make_aware(datetime(year, month, day, hour, minute))


class BusinessDateTests(ApiTestCase):
    """A punch's business day, which is NOT simply its calendar date."""

    def test_punch_after_cutover_belongs_to_its_own_day(self):
        self.assertEqual(
            attendance.business_date_for(self.branch_a, aware(2026, 3, 10, 10, 30)),
            date(2026, 3, 10),
        )

    def test_punch_before_cutover_belongs_to_the_previous_day(self):
        # 01:30 clock-out from a shift that started the evening before.
        self.assertEqual(
            attendance.business_date_for(self.branch_a, aware(2026, 3, 11, 1, 30)),
            date(2026, 3, 10),
        )

    def test_cutover_hour_itself_starts_the_new_day(self):
        setting = BranchScheduleSetting.objects.get(branch=self.branch_a)
        self.assertEqual(setting.attendance_day_cutover_hour, 5)
        self.assertEqual(
            attendance.business_date_for(self.branch_a, aware(2026, 3, 11, 5, 0)),
            date(2026, 3, 11),
        )

    def test_branch_can_retune_its_own_cutover(self):
        setting = BranchScheduleSetting.objects.get(branch=self.branch_a)
        setting.attendance_day_cutover_hour = 3
        setting.save()
        # 04:00 is now after the cutover, so it is its own day.
        self.assertEqual(
            attendance.business_date_for(self.branch_a, aware(2026, 3, 11, 4, 0)),
            date(2026, 3, 11),
        )

    def test_branch_without_a_schedule_setting_still_resolves_a_day(self):
        BranchScheduleSetting.objects.filter(branch=self.branch_a).delete()
        self.assertEqual(
            attendance.business_date_for(self.branch_a, aware(2026, 3, 11, 1, 30)),
            date(2026, 3, 10),
        )


class SummarizePunchesTests(ApiTestCase):
    """Reducing a day's punches to start / end / break, including the
    incomplete days that are the whole reason a manager reviews this."""

    def setUp(self):
        super().setUp()
        self.employee = self.staff_employee

    def punch(self, kind, at):
        return AttendancePunch.objects.create(
            employee=self.employee, branch=self.branch_a, work_date=date(2026, 3, 10),
            kind=kind, punched_at=at,
        )

    def summarize(self):
        punches = list(AttendancePunch.objects.filter(employee=self.employee).order_by('punched_at'))
        return attendance.summarize_punches(punches)

    def test_simple_day_uses_first_in_and_last_out(self):
        self.punch(AttendancePunch.Kind.CLOCK_IN, aware(2026, 3, 10, 9, 0))
        self.punch(AttendancePunch.Kind.CLOCK_OUT, aware(2026, 3, 10, 17, 30))
        start, end, break_minutes, crosses, problems = self.summarize()
        self.assertEqual((start, end, break_minutes, crosses), (time(9, 0), time(17, 30), 0, False))
        self.assertEqual(problems, [])

    def test_break_pair_is_summed_into_break_minutes(self):
        self.punch(AttendancePunch.Kind.CLOCK_IN, aware(2026, 3, 10, 9, 0))
        self.punch(AttendancePunch.Kind.BREAK_START, aware(2026, 3, 10, 12, 0))
        self.punch(AttendancePunch.Kind.BREAK_END, aware(2026, 3, 10, 13, 0))
        self.punch(AttendancePunch.Kind.CLOCK_OUT, aware(2026, 3, 10, 17, 0))
        _, _, break_minutes, _, problems = self.summarize()
        self.assertEqual(break_minutes, 60)
        self.assertEqual(problems, [])

    def test_unclosed_break_is_not_counted_and_is_reported(self):
        # Guessing a length here would directly reduce someone's paid time.
        self.punch(AttendancePunch.Kind.CLOCK_IN, aware(2026, 3, 10, 9, 0))
        self.punch(AttendancePunch.Kind.BREAK_START, aware(2026, 3, 10, 12, 0))
        self.punch(AttendancePunch.Kind.CLOCK_OUT, aware(2026, 3, 10, 17, 0))
        _, _, break_minutes, _, problems = self.summarize()
        self.assertEqual(break_minutes, 0)
        self.assertIn('break-not-closed', problems)

    def test_missing_clock_out_is_reported_not_invented(self):
        self.punch(AttendancePunch.Kind.CLOCK_IN, aware(2026, 3, 10, 9, 0))
        start, end, _, _, problems = self.summarize()
        self.assertEqual(start, time(9, 0))
        self.assertIsNone(end)
        self.assertIn('missing-clock-out', problems)

    def test_overnight_day_sets_crosses_midnight(self):
        self.punch(AttendancePunch.Kind.CLOCK_IN, aware(2026, 3, 10, 22, 0))
        self.punch(AttendancePunch.Kind.CLOCK_OUT, aware(2026, 3, 11, 1, 30))
        start, end, _, crosses, problems = self.summarize()
        self.assertEqual((start, end, crosses), (time(22, 0), time(1, 30), True))
        self.assertEqual(problems, [])


class ExceptionMinutesTests(ApiTestCase):
    """Late / early-leave minutes against the planned shift."""

    def setUp(self):
        super().setUp()
        self.employee = self.staff_employee
        self.period = SchedulePeriod.objects.create(
            branch=self.branch_a, month=date(2026, 3, 1),
            start_date=date(2026, 3, 1), end_date=date(2026, 3, 31),
        )
        self.shift = Shift.objects.create(
            period=self.period, branch=self.branch_a, employee=self.employee,
            work_date=date(2026, 3, 10), planned_start=time(9, 0), planned_end=time(17, 0),
        )

    def record(self, start, end, **kwargs):
        return ActualWorkRecord.objects.create(
            employee=self.employee, branch=self.branch_a, work_date=date(2026, 3, 10),
            shift=self.shift, actual_start=start, actual_end=end, **kwargs,
        )

    def test_on_time_day_has_no_deviation(self):
        record = attendance.apply_exception_minutes(self.record(time(9, 0), time(17, 0)))
        self.assertEqual((record.late_minutes, record.early_leave_minutes), (0, 0))

    def test_late_arrival_is_recorded_in_minutes(self):
        record = attendance.apply_exception_minutes(self.record(time(9, 25), time(17, 0)))
        self.assertEqual(record.late_minutes, 25)

    def test_early_departure_is_recorded_in_minutes(self):
        record = attendance.apply_exception_minutes(self.record(time(9, 0), time(16, 40)))
        self.assertEqual(record.early_leave_minutes, 20)

    def test_grace_period_is_subtracted_not_just_compared(self):
        setting = BranchScheduleSetting.objects.get(branch=self.branch_a)
        setting.late_grace_minutes = 10
        setting.save()
        # 25 minutes late, 10 forgiven -> 15 recorded, not 25 and not 0.
        record = attendance.apply_exception_minutes(self.record(time(9, 25), time(17, 0)))
        self.assertEqual(record.late_minutes, 15)

    def test_within_grace_is_not_late_at_all(self):
        setting = BranchScheduleSetting.objects.get(branch=self.branch_a)
        setting.late_grace_minutes = 10
        setting.save()
        record = attendance.apply_exception_minutes(self.record(time(9, 5), time(17, 0)))
        self.assertEqual(record.late_minutes, 0)

    def test_arriving_early_is_never_negative_lateness(self):
        record = attendance.apply_exception_minutes(self.record(time(8, 30), time(17, 30)))
        self.assertEqual((record.late_minutes, record.early_leave_minutes), (0, 0))

    def test_absent_day_reports_no_deviation(self):
        record = attendance.apply_exception_minutes(
            self.record(None, None, absent=True),
        )
        self.assertEqual((record.late_minutes, record.early_leave_minutes), (0, 0))

    def test_unscheduled_cover_is_not_late(self):
        other = StaffMember.objects.create(name='DEMO/TEST cover', branch=self.branch_a)
        record = ActualWorkRecord.objects.create(
            employee=other, branch=self.branch_a, work_date=date(2026, 3, 10),
            actual_start=time(13, 0), actual_end=time(20, 0),
        )
        attendance.apply_exception_minutes(record)
        self.assertEqual((record.late_minutes, record.early_leave_minutes), (0, 0))

    def test_overnight_shift_end_is_measured_on_the_next_day(self):
        self.shift.planned_start = time(22, 0)
        self.shift.planned_end = time(2, 0)
        self.shift.crosses_midnight = True
        self.shift.save()
        record = self.record(time(22, 0), time(1, 30), crosses_midnight=True)
        attendance.apply_exception_minutes(record)
        # Left at 01:30 against a 02:00 end = 30 minutes early. Without
        # next-day handling this would read as a ~20-hour early departure.
        self.assertEqual(record.early_leave_minutes, 30)


class PunchApiTests(ApiTestCase):
    """The employee self-service clock, end to end through the API."""

    def punch(self, kind):
        return self.client.post('/api/attendance-punches/', {'kind': kind})

    def test_staff_can_clock_themselves_in(self):
        self.login_as(self.staff_user)
        resp = self.punch(AttendancePunch.Kind.CLOCK_IN)
        self.assertEqual(resp.status_code, 201, resp.content)
        punch = AttendancePunch.objects.get()
        self.assertEqual(punch.employee_id, self.staff_employee.id)
        self.assertEqual(punch.source, AttendancePunch.Source.SELF)

    def test_punch_time_comes_from_the_server_not_the_client(self):
        self.login_as(self.staff_user)
        before = timezone.now()
        resp = self.client.post('/api/attendance-punches/', {
            'kind': AttendancePunch.Kind.CLOCK_IN,
            # A phone with a deliberately wrong clock.
            'punched_at': '2020-01-01T03:00:00Z',
            'work_date': '2020-01-01',
        })
        self.assertEqual(resp.status_code, 201, resp.content)
        punch = AttendancePunch.objects.get()
        self.assertGreaterEqual(punch.punched_at, before)
        self.assertNotEqual(punch.work_date, date(2020, 1, 1))

    def test_staff_cannot_punch_for_another_employee(self):
        other = StaffMember.objects.create(name='DEMO/TEST other', branch=self.branch_a)
        self.login_as(self.staff_user)
        resp = self.client.post('/api/attendance-punches/', {
            'kind': AttendancePunch.Kind.CLOCK_IN, 'employee': other.id,
        })
        self.assertEqual(resp.status_code, 201, resp.content)
        # The submitted employee id is ignored, not honoured.
        self.assertEqual(AttendancePunch.objects.get().employee_id, self.staff_employee.id)

    def test_punch_order_is_enforced_server_side(self):
        self.login_as(self.staff_user)
        # Clock out with no clock in.
        resp = self.punch(AttendancePunch.Kind.CLOCK_OUT)
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('punch-not-allowed-clock-out', str(resp.content))

    def test_cannot_clock_in_twice(self):
        self.login_as(self.staff_user)
        self.assertEqual(self.punch(AttendancePunch.Kind.CLOCK_IN).status_code, 201)
        self.assertEqual(self.punch(AttendancePunch.Kind.CLOCK_IN).status_code, 400)

    def test_cannot_clock_out_while_on_break(self):
        self.login_as(self.staff_user)
        self.punch(AttendancePunch.Kind.CLOCK_IN)
        self.punch(AttendancePunch.Kind.BREAK_START)
        self.assertEqual(self.punch(AttendancePunch.Kind.CLOCK_OUT).status_code, 400)
        self.assertEqual(self.punch(AttendancePunch.Kind.BREAK_END).status_code, 201)
        self.assertEqual(self.punch(AttendancePunch.Kind.CLOCK_OUT).status_code, 201)

    def test_punches_cannot_be_edited_or_deleted(self):
        self.login_as(self.staff_user)
        self.punch(AttendancePunch.Kind.CLOCK_IN)
        punch = AttendancePunch.objects.get()
        self.logout()
        self.login_as(self.admin)
        self.assertEqual(self.client.patch(f'/api/attendance-punches/{punch.id}/', {}).status_code, 405)
        self.assertEqual(self.client.delete(f'/api/attendance-punches/{punch.id}/').status_code, 405)

    def test_branch_can_disable_self_punch(self):
        setting = BranchScheduleSetting.objects.get(branch=self.branch_a)
        setting.self_punch_enabled = False
        setting.save()
        self.login_as(self.staff_user)
        self.assertEqual(self.punch(AttendancePunch.Kind.CLOCK_IN).status_code, 403)

    def test_manager_can_still_punch_when_self_punch_is_disabled(self):
        setting = BranchScheduleSetting.objects.get(branch=self.branch_a)
        setting.self_punch_enabled = False
        setting.save()
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/attendance-punches/', {
            'kind': AttendancePunch.Kind.CLOCK_IN, 'employee': self.staff_employee.id,
        })
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(AttendancePunch.objects.get().source, AttendancePunch.Source.MANAGER)

    def test_today_endpoint_tells_the_employee_which_action_is_next(self):
        self.login_as(self.staff_user)
        resp = self.client.get('/api/attendance-punches/today/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.data['canClockIn'])
        self.assertFalse(resp.data['canClockOut'])
        self.punch(AttendancePunch.Kind.CLOCK_IN)
        resp = self.client.get('/api/attendance-punches/today/')
        self.assertFalse(resp.data['canClockIn'])
        self.assertTrue(resp.data['canClockOut'])
        self.assertTrue(resp.data['canStartBreak'])

    def test_a_full_day_of_punches_produces_the_attendance_record(self):
        self.login_as(self.staff_user)
        self.punch(AttendancePunch.Kind.CLOCK_IN)
        self.punch(AttendancePunch.Kind.CLOCK_OUT)
        record = ActualWorkRecord.objects.get(employee=self.staff_employee)
        self.assertEqual(record.source, ActualWorkRecord.Source.PUNCH)
        self.assertIsNotNone(record.actual_start)
        self.assertIsNotNone(record.actual_end)


class PayrollSafetyTests(ApiTestCase):
    """The invariant the whole design rests on: a punch is evidence, a
    manager's confirmation is authority. If any of these break, an employee
    can move their own pay."""

    def test_punch_derived_record_is_pending_not_confirmed(self):
        self.login_as(self.staff_user)
        self.client.post('/api/attendance-punches/', {'kind': AttendancePunch.Kind.CLOCK_IN})
        self.client.post('/api/attendance-punches/', {'kind': AttendancePunch.Kind.CLOCK_OUT})
        record = ActualWorkRecord.objects.get(employee=self.staff_employee)
        # PENDING is exactly what the wage engine excludes.
        self.assertEqual(record.status, ActualWorkRecord.Status.PENDING)

    def test_pending_punch_records_are_invisible_to_the_wage_engine(self):
        self.login_as(self.staff_user)
        self.client.post('/api/attendance-punches/', {'kind': AttendancePunch.Kind.CLOCK_IN})
        self.client.post('/api/attendance-punches/', {'kind': AttendancePunch.Kind.CLOCK_OUT})
        # The exact filter wages/calculation.py applies.
        payable = ActualWorkRecord.objects.filter(
            branch=self.branch_a, absent=False,
            status__in=[ActualWorkRecord.Status.MANAGER_CONFIRMED, ActualWorkRecord.Status.ADMIN_LOCKED],
        )
        self.assertEqual(payable.count(), 0)

    def test_a_confirmed_day_is_not_rewritten_by_a_later_punch(self):
        work_date = attendance.business_date_for(self.branch_a, timezone.now())
        record = ActualWorkRecord.objects.create(
            employee=self.staff_employee, branch=self.branch_a, work_date=work_date,
            actual_start=time(9, 0), actual_end=time(17, 0),
            status=ActualWorkRecord.Status.MANAGER_CONFIRMED,
        )
        self.login_as(self.staff_user)
        self.client.post('/api/attendance-punches/', {'kind': AttendancePunch.Kind.CLOCK_IN})
        record.refresh_from_db()
        self.assertEqual(record.actual_start, time(9, 0))
        self.assertEqual(record.status, ActualWorkRecord.Status.MANAGER_CONFIRMED)
        # The punch is still recorded — it is evidence, it just doesn't apply.
        self.assertEqual(AttendancePunch.objects.count(), 1)

    def test_a_locked_day_is_never_rewritten(self):
        work_date = attendance.business_date_for(self.branch_a, timezone.now())
        record = ActualWorkRecord.objects.create(
            employee=self.staff_employee, branch=self.branch_a, work_date=work_date,
            actual_start=time(9, 0), actual_end=time(17, 0),
            status=ActualWorkRecord.Status.ADMIN_LOCKED,
        )
        # A late punch really does arrive on the locked day — this is not
        # the trivially-safe "there were no punches" case.
        AttendancePunch.objects.create(
            employee=self.staff_employee, branch=self.branch_a, work_date=work_date,
            kind=AttendancePunch.Kind.CLOCK_IN, punched_at=timezone.now(),
        )
        _, applied, problems = attendance.rebuild_from_punches(
            self.staff_employee, self.branch_a, work_date,
        )
        self.assertFalse(applied)
        self.assertIn('record-already-confirmed', problems)
        record.refresh_from_db()
        self.assertEqual(record.status, ActualWorkRecord.Status.ADMIN_LOCKED)

    def test_approved_correction_still_lands_as_pending(self):
        correction = AttendanceCorrectionRequest.objects.create(
            employee=self.staff_employee, branch=self.branch_a, work_date=date(2026, 3, 10),
            requested_start=time(9, 0), requested_end=time(18, 0), reason='forgot to clock out',
        )
        self.login_as(self.branch_a_user)
        resp = self.client.post(f'/api/attendance-corrections/{correction.id}/approve/')
        self.assertEqual(resp.status_code, 200, resp.content)
        record = ActualWorkRecord.objects.get(employee=self.staff_employee, work_date=date(2026, 3, 10))
        self.assertEqual(record.status, ActualWorkRecord.Status.PENDING)

    def test_staff_cannot_write_an_attendance_record_directly(self):
        self.login_as(self.staff_user)
        resp = self.client.post('/api/actual-work-records/', {
            'employee': self.staff_employee.id, 'branch': self.branch_a.id,
            'work_date': '2026-03-10', 'actual_start': '09:00', 'actual_end': '23:00',
        })
        self.assertIn(resp.status_code, (403, 400))
        self.assertEqual(ActualWorkRecord.objects.count(), 0)

    def test_staff_cannot_confirm_their_own_attendance(self):
        record = ActualWorkRecord.objects.create(
            employee=self.staff_employee, branch=self.branch_a, work_date=date(2026, 3, 10),
            actual_start=time(9, 0), actual_end=time(17, 0),
        )
        self.login_as(self.staff_user)
        resp = self.client.post(
            '/api/actual-work-records/bulk_confirm/', {'ids': [record.id]}, format='json',
        )
        self.assertEqual(resp.status_code, 403)
        record.refresh_from_db()
        self.assertEqual(record.status, ActualWorkRecord.Status.PENDING)


class CorrectionRequestTests(ApiTestCase):
    """The 補正申請 submit / decide flow."""

    def submit(self, **overrides):
        payload = {
            'work_date': '2026-03-10', 'requested_start': '09:00', 'requested_end': '18:00',
            'reason': 'forgot to clock out',
        }
        payload.update(overrides)
        return self.client.post('/api/attendance-corrections/', payload)

    def test_staff_can_submit_for_themselves(self):
        self.login_as(self.staff_user)
        resp = self.submit()
        self.assertEqual(resp.status_code, 201, resp.content)
        correction = AttendanceCorrectionRequest.objects.get()
        self.assertEqual(correction.employee_id, self.staff_employee.id)
        self.assertEqual(correction.status, AttendanceCorrectionRequest.Status.PENDING)

    def test_reason_is_required(self):
        self.login_as(self.staff_user)
        self.assertEqual(self.submit(reason='   ').status_code, 400)

    def test_a_request_that_changes_nothing_is_rejected(self):
        self.login_as(self.staff_user)
        resp = self.client.post('/api/attendance-corrections/', {
            'work_date': '2026-03-10', 'reason': 'something happened',
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn('correction-nothing-requested', str(resp.content))

    def test_absent_request_must_not_also_carry_times(self):
        self.login_as(self.staff_user)
        resp = self.submit(requested_absent=True)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('correction-absent-with-times', str(resp.content))

    def test_end_before_start_is_rejected(self):
        self.login_as(self.staff_user)
        resp = self.submit(requested_start='18:00', requested_end='09:00')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('correction-invalid-time-range', str(resp.content))

    def test_only_one_pending_request_per_day(self):
        self.login_as(self.staff_user)
        self.assertEqual(self.submit().status_code, 201)
        resp = self.submit()
        self.assertEqual(resp.status_code, 400)
        self.assertIn('correction-already-pending-for-date', str(resp.content))

    def test_a_new_request_is_allowed_once_the_previous_one_is_decided(self):
        self.login_as(self.staff_user)
        self.submit()
        correction = AttendanceCorrectionRequest.objects.get()
        self.logout()
        self.login_as(self.branch_a_user)
        self.client.post(f'/api/attendance-corrections/{correction.id}/reject/', {'note': 'no record of this'})
        self.logout()
        self.login_as(self.staff_user)
        self.assertEqual(self.submit().status_code, 201)

    def test_staff_cannot_approve_anything(self):
        self.login_as(self.staff_user)
        self.submit()
        correction = AttendanceCorrectionRequest.objects.get()
        resp = self.client.post(f'/api/attendance-corrections/{correction.id}/approve/')
        self.assertEqual(resp.status_code, 403)
        correction.refresh_from_db()
        self.assertEqual(correction.status, AttendanceCorrectionRequest.Status.PENDING)

    def test_rejection_requires_a_note(self):
        self.login_as(self.staff_user)
        self.submit()
        correction = AttendanceCorrectionRequest.objects.get()
        self.logout()
        self.login_as(self.branch_a_user)
        self.assertEqual(
            self.client.post(f'/api/attendance-corrections/{correction.id}/reject/', {}).status_code, 400,
        )

    def test_approval_applies_the_requested_times(self):
        self.login_as(self.staff_user)
        self.submit()
        correction = AttendanceCorrectionRequest.objects.get()
        self.logout()
        self.login_as(self.branch_a_user)
        resp = self.client.post(f'/api/attendance-corrections/{correction.id}/approve/')
        self.assertEqual(resp.status_code, 200, resp.content)
        record = ActualWorkRecord.objects.get(work_date=date(2026, 3, 10))
        self.assertEqual((record.actual_start, record.actual_end), (time(9, 0), time(18, 0)))
        self.assertEqual(record.source, ActualWorkRecord.Source.CORRECTION)

    def test_approving_an_absence_clears_any_worked_times(self):
        ActualWorkRecord.objects.create(
            employee=self.staff_employee, branch=self.branch_a, work_date=date(2026, 3, 10),
            actual_start=time(9, 0), actual_end=time(17, 0),
        )
        self.login_as(self.staff_user)
        self.client.post('/api/attendance-corrections/', {
            'work_date': '2026-03-10', 'requested_absent': True, 'reason': 'was off sick',
        })
        correction = AttendanceCorrectionRequest.objects.get()
        self.logout()
        self.login_as(self.branch_a_user)
        self.client.post(f'/api/attendance-corrections/{correction.id}/approve/')
        record = ActualWorkRecord.objects.get(work_date=date(2026, 3, 10))
        self.assertTrue(record.absent)
        # A day must never read as both absent and worked.
        self.assertIsNone(record.actual_start)
        self.assertIsNone(record.actual_end)

    def test_approving_against_a_locked_day_is_refused_not_silently_dropped(self):
        ActualWorkRecord.objects.create(
            employee=self.staff_employee, branch=self.branch_a, work_date=date(2026, 3, 10),
            actual_start=time(9, 0), actual_end=time(17, 0),
            status=ActualWorkRecord.Status.ADMIN_LOCKED,
        )
        self.login_as(self.staff_user)
        self.submit()
        correction = AttendanceCorrectionRequest.objects.get()
        self.logout()
        self.login_as(self.branch_a_user)
        resp = self.client.post(f'/api/attendance-corrections/{correction.id}/approve/')
        self.assertEqual(resp.status_code, 400)
        correction.refresh_from_db()
        self.assertEqual(correction.status, AttendanceCorrectionRequest.Status.PENDING)

    def test_a_decided_request_cannot_be_decided_again(self):
        self.login_as(self.staff_user)
        self.submit()
        correction = AttendanceCorrectionRequest.objects.get()
        self.logout()
        self.login_as(self.branch_a_user)
        self.client.post(f'/api/attendance-corrections/{correction.id}/approve/')
        resp = self.client.post(f'/api/attendance-corrections/{correction.id}/reject/', {'note': 'changed my mind'})
        self.assertEqual(resp.status_code, 400)

    def test_employee_can_withdraw_their_own_pending_request(self):
        self.login_as(self.staff_user)
        self.submit()
        correction = AttendanceCorrectionRequest.objects.get()
        resp = self.client.post(f'/api/attendance-corrections/{correction.id}/withdraw/')
        self.assertEqual(resp.status_code, 200, resp.content)
        correction.refresh_from_db()
        self.assertEqual(correction.status, AttendanceCorrectionRequest.Status.WITHDRAWN)


class AttendancePermissionTests(ApiTestCase):
    """Role boundaries inside one Organization."""

    def setUp(self):
        super().setUp()
        self.other_employee = StaffMember.objects.create(name='DEMO/TEST b-staff', branch=self.branch_b)

    def test_staff_only_sees_their_own_punches(self):
        AttendancePunch.objects.create(
            employee=self.staff_employee, branch=self.branch_a, work_date=date(2026, 3, 10),
            kind=AttendancePunch.Kind.CLOCK_IN, punched_at=aware(2026, 3, 10, 9, 0),
        )
        AttendancePunch.objects.create(
            employee=self.other_employee, branch=self.branch_b, work_date=date(2026, 3, 10),
            kind=AttendancePunch.Kind.CLOCK_IN, punched_at=aware(2026, 3, 10, 9, 0),
        )
        self.login_as(self.staff_user)
        resp = self.client.get('/api/attendance-punches/')
        self.assertEqual(len(resp.data['results'] if 'results' in resp.data else resp.data), 1)

    def test_branch_account_cannot_punch_for_another_branch(self):
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/attendance-punches/', {
            'kind': AttendancePunch.Kind.CLOCK_IN, 'employee': self.other_employee.id,
        })
        self.assertEqual(resp.status_code, 403)

    def test_branch_account_only_sees_its_own_branch_corrections(self):
        AttendanceCorrectionRequest.objects.create(
            employee=self.staff_employee, branch=self.branch_a, work_date=date(2026, 3, 10),
            requested_absent=True, reason='a',
        )
        AttendanceCorrectionRequest.objects.create(
            employee=self.other_employee, branch=self.branch_b, work_date=date(2026, 3, 10),
            requested_absent=True, reason='b',
        )
        self.login_as(self.branch_a_user)
        resp = self.client.get('/api/attendance-corrections/')
        rows = resp.data['results'] if 'results' in resp.data else resp.data
        self.assertEqual([r['branch'] for r in rows], [self.branch_a.id])

    def test_admin_sees_every_branch_in_its_own_organization(self):
        AttendanceCorrectionRequest.objects.create(
            employee=self.staff_employee, branch=self.branch_a, work_date=date(2026, 3, 10),
            requested_absent=True, reason='a',
        )
        AttendanceCorrectionRequest.objects.create(
            employee=self.other_employee, branch=self.branch_b, work_date=date(2026, 3, 10),
            requested_absent=True, reason='b',
        )
        self.login_as(self.admin)
        resp = self.client.get('/api/attendance-corrections/')
        rows = resp.data['results'] if 'results' in resp.data else resp.data
        self.assertEqual(len(rows), 2)

    def test_change_log_is_read_only_for_everyone_including_admin(self):
        self.login_as(self.admin)
        resp = self.client.post('/api/attendance-change-logs/', {})
        self.assertEqual(resp.status_code, 405)

    def test_staff_account_with_no_linked_employee_gets_nothing(self):
        self.staff_user.staff_member = None
        self.staff_user.save()
        self.login_as(self.staff_user)
        resp = self.client.get('/api/attendance-punches/')
        rows = resp.data['results'] if 'results' in resp.data else resp.data
        self.assertEqual(len(rows), 0)
        self.assertEqual(
            self.client.post('/api/attendance-punches/', {'kind': AttendancePunch.Kind.CLOCK_IN}).status_code,
            403,
        )


class AttendanceTenantIsolationTests(TwoOrganizationApiTestCase):
    """Cross-Organization isolation — the leak that would end the product."""

    def setUp(self):
        super().setUp()
        self.punch_b = AttendancePunch.objects.create(
            employee=self.staff_b1, branch=self.branch_b1, work_date=date(2026, 3, 10),
            kind=AttendancePunch.Kind.CLOCK_IN, punched_at=aware(2026, 3, 10, 9, 0),
        )
        self.correction_b = AttendanceCorrectionRequest.objects.create(
            employee=self.staff_b1, branch=self.branch_b1, work_date=date(2026, 3, 10),
            requested_absent=True, reason='org B business',
        )

    def test_admin_a_cannot_list_org_b_punches(self):
        self.login_as(self.admin_a)
        resp = self.client.get('/api/attendance-punches/')
        rows = resp.data['results'] if 'results' in resp.data else resp.data
        self.assertEqual(rows, [])

    def test_admin_a_cannot_retrieve_an_org_b_punch_by_id(self):
        self.login_as(self.admin_a)
        self.assertEqual(self.client.get(f'/api/attendance-punches/{self.punch_b.id}/').status_code, 404)

    def test_admin_a_cannot_punch_for_an_org_b_employee(self):
        self.login_as(self.admin_a)
        resp = self.client.post('/api/attendance-punches/', {
            'kind': AttendancePunch.Kind.CLOCK_IN, 'employee': self.staff_b1.id,
        })
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(AttendancePunch.objects.filter(employee=self.staff_b1).count(), 1)

    def test_admin_a_cannot_approve_an_org_b_correction(self):
        self.login_as(self.admin_a)
        resp = self.client.post(f'/api/attendance-corrections/{self.correction_b.id}/approve/')
        self.assertEqual(resp.status_code, 404)
        self.correction_b.refresh_from_db()
        self.assertEqual(self.correction_b.status, AttendanceCorrectionRequest.Status.PENDING)

    def test_admin_a_cannot_read_org_b_change_logs(self):
        AttendanceChangeLog.objects.create(
            employee=self.staff_b1, branch=self.branch_b1, work_date=date(2026, 3, 10),
            source=AttendanceChangeLog.Source.MANUAL, before=None, after=None,
        )
        self.login_as(self.admin_a)
        resp = self.client.get('/api/attendance-change-logs/')
        rows = resp.data['results'] if 'results' in resp.data else resp.data
        self.assertEqual(rows, [])

    def test_branch_account_cannot_see_a_sibling_branch_in_its_own_org(self):
        AttendancePunch.objects.create(
            employee=self.staff_a1, branch=self.branch_a1, work_date=date(2026, 3, 10),
            kind=AttendancePunch.Kind.CLOCK_IN, punched_at=aware(2026, 3, 10, 9, 0),
        )
        self.login_as(self.branch_a2_user)
        resp = self.client.get('/api/attendance-punches/')
        rows = resp.data['results'] if 'results' in resp.data else resp.data
        self.assertEqual(rows, [])


class AttendanceChangeLogTests(ApiTestCase):
    """Every change to an attendance record leaves a trail."""

    def test_a_punch_writes_a_log_entry(self):
        self.login_as(self.staff_user)
        self.client.post('/api/attendance-punches/', {'kind': AttendancePunch.Kind.CLOCK_IN})
        entry = AttendanceChangeLog.objects.get()
        self.assertEqual(entry.source, AttendanceChangeLog.Source.PUNCH)
        self.assertEqual(entry.changed_by_id, self.staff_user.id)

    def test_a_manager_edit_records_before_and_after(self):
        record = ActualWorkRecord.objects.create(
            employee=self.staff_employee, branch=self.branch_a, work_date=date(2026, 3, 10),
            actual_start=time(9, 0), actual_end=time(17, 0),
        )
        self.login_as(self.branch_a_user)
        resp = self.client.patch(f'/api/actual-work-records/{record.id}/', {
            'actual_end': '19:00', 'adjustment_reason': 'stayed to close',
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        entry = AttendanceChangeLog.objects.filter(source=AttendanceChangeLog.Source.MANUAL).latest('changed_at')
        self.assertEqual(entry.before['actual_end'], '17:00:00')
        self.assertEqual(entry.after['actual_end'], '19:00:00')
        self.assertEqual(entry.reason, 'stayed to close')

    def test_confirming_is_logged(self):
        record = ActualWorkRecord.objects.create(
            employee=self.staff_employee, branch=self.branch_a, work_date=date(2026, 3, 10),
            actual_start=time(9, 0), actual_end=time(17, 0),
        )
        self.login_as(self.branch_a_user)
        # format='json' matters: bulk_confirm reads request.data['ids']
        # as a list, and form encoding would collapse it to a string
        # (which `id__in` would then iterate character by character).
        resp = self.client.post(
            '/api/actual-work-records/bulk_confirm/', {'ids': [record.id]}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['confirmed'], 1, resp.data)
        entry = AttendanceChangeLog.objects.filter(source=AttendanceChangeLog.Source.STATUS).latest('changed_at')
        self.assertEqual(entry.before['status'], ActualWorkRecord.Status.PENDING)
        self.assertEqual(entry.after['status'], ActualWorkRecord.Status.MANAGER_CONFIRMED)

    def test_the_log_outlives_the_record_it_describes(self):
        record = ActualWorkRecord.objects.create(
            employee=self.staff_employee, branch=self.branch_a, work_date=date(2026, 3, 10),
            actual_start=time(9, 0), actual_end=time(17, 0),
        )
        self.login_as(self.branch_a_user)
        self.client.delete(f'/api/actual-work-records/{record.id}/')
        entry = AttendanceChangeLog.objects.latest('changed_at')
        self.assertIsNone(entry.record_id)
        self.assertEqual(entry.work_date, date(2026, 3, 10))
        self.assertEqual(entry.employee_id, self.staff_employee.id)
        self.assertEqual(entry.before['actual_start'], '09:00:00')

    def test_an_approved_correction_links_its_log_entry_back_to_the_request(self):
        correction = AttendanceCorrectionRequest.objects.create(
            employee=self.staff_employee, branch=self.branch_a, work_date=date(2026, 3, 10),
            requested_start=time(9, 0), requested_end=time(18, 0), reason='forgot to clock out',
        )
        self.login_as(self.branch_a_user)
        self.client.post(f'/api/attendance-corrections/{correction.id}/approve/')
        entry = AttendanceChangeLog.objects.get(source=AttendanceChangeLog.Source.CORRECTION)
        self.assertEqual(entry.correction_request_id, correction.id)


class ExceptionFilterTests(ApiTestCase):
    """The manager's "show me only what needs attention" filter."""

    def setUp(self):
        super().setUp()
        self.normal = ActualWorkRecord.objects.create(
            employee=self.staff_employee, branch=self.branch_a, work_date=date(2026, 3, 10),
            actual_start=time(9, 0), actual_end=time(17, 0),
        )
        late_employee = StaffMember.objects.create(name='DEMO/TEST late', branch=self.branch_a)
        self.late = ActualWorkRecord.objects.create(
            employee=late_employee, branch=self.branch_a, work_date=date(2026, 3, 10),
            actual_start=time(9, 30), actual_end=time(17, 0), late_minutes=30,
        )
        absent_employee = StaffMember.objects.create(name='DEMO/TEST absent', branch=self.branch_a)
        self.absent = ActualWorkRecord.objects.create(
            employee=absent_employee, branch=self.branch_a, work_date=date(2026, 3, 10), absent=True,
        )
        unfinished_employee = StaffMember.objects.create(name='DEMO/TEST unfinished', branch=self.branch_a)
        self.unfinished = ActualWorkRecord.objects.create(
            employee=unfinished_employee, branch=self.branch_a, work_date=date(2026, 3, 10),
            actual_start=time(9, 0), actual_end=None,
        )

    def ids(self, query):
        resp = self.client.get(f'/api/actual-work-records/{query}')
        rows = resp.data['results'] if 'results' in resp.data else resp.data
        return {r['id'] for r in rows}

    def test_exception_true_returns_late_absent_and_unfinished_days(self):
        self.login_as(self.branch_a_user)
        self.assertEqual(
            self.ids('?exception=true'),
            {self.late.id, self.absent.id, self.unfinished.id},
        )

    def test_exception_false_is_the_exact_complement(self):
        self.login_as(self.branch_a_user)
        self.assertEqual(self.ids('?exception=false'), {self.normal.id})

    def test_the_two_filters_partition_the_whole_month(self):
        self.login_as(self.branch_a_user)
        self.assertEqual(
            self.ids('?exception=true') | self.ids('?exception=false'),
            self.ids(''),
        )


class HistoricalExceptionMinuteBackfillTests(ApiTestCase):
    """Migration 0009: existing attendance gets its real late / early-leave
    minutes, so the manager's "only show exceptions" filter tells the truth
    about months that predate those two columns.

    The migration's function is called directly with the live app registry.
    Its historical models are structurally identical to the runtime ones
    here, and what needs pinning is the arithmetic and what it refuses to
    touch — not Django's own executor.
    """

    def setUp(self):
        super().setUp()
        self.period = SchedulePeriod.objects.create(
            branch=self.branch_a, month=date(2026, 3, 1),
            start_date=date(2026, 3, 1), end_date=date(2026, 3, 31),
            status=SchedulePeriod.Status.PUBLISHED,
        )

    def pre_migration_record(self, *, planned, actual, crosses_midnight=False,
                             shift_crosses_midnight=False, absent=False, with_shift=True):
        """A record in the state 0007 leaves behind: real times, but both
        deviation columns still at their default 0."""
        shift = None
        if with_shift:
            shift = Shift.objects.create(
                period=self.period, branch=self.branch_a, employee=self.staff_employee,
                work_date=date(2026, 3, 10),
                planned_start=planned[0], planned_end=planned[1],
                crosses_midnight=shift_crosses_midnight,
            )
        record = ActualWorkRecord.objects.create(
            employee=self.staff_employee, branch=self.branch_a, work_date=date(2026, 3, 10),
            shift=shift, absent=absent,
            actual_start=actual[0], actual_end=actual[1], crosses_midnight=crosses_midnight,
            status=ActualWorkRecord.Status.MANAGER_CONFIRMED,
        )
        # ActualWorkRecord.save() does not derive these (the service layer
        # does), but be explicit: the point of the test is that they START
        # at 0, exactly as the schema migration left them.
        ActualWorkRecord.objects.filter(pk=record.pk).update(late_minutes=0, early_leave_minutes=0)
        record.refresh_from_db()
        return record

    @staticmethod
    def run_backfill():
        from importlib import import_module

        from django.apps import apps as live_apps
        module = import_module('scheduling.migrations.0009_backfill_attendance_exception_minutes')
        module.fill_exception_minutes(live_apps, None)
        return module

    def test_a_historical_late_arrival_gets_its_minutes(self):
        record = self.pre_migration_record(planned=(time(10, 0), time(18, 0)), actual=(time(10, 25), time(18, 0)))
        self.run_backfill()
        record.refresh_from_db()
        self.assertEqual(record.late_minutes, 25)
        self.assertEqual(record.early_leave_minutes, 0)

    def test_a_historical_early_departure_gets_its_minutes(self):
        record = self.pre_migration_record(planned=(time(10, 0), time(18, 0)), actual=(time(10, 0), time(17, 30)))
        self.run_backfill()
        record.refresh_from_db()
        self.assertEqual(record.late_minutes, 0)
        self.assertEqual(record.early_leave_minutes, 30)

    def test_the_branch_grace_period_is_honoured(self):
        setting = BranchScheduleSetting.objects.get(branch=self.branch_a)
        setting.late_grace_minutes = 10
        setting.early_leave_grace_minutes = 5
        setting.save()
        record = self.pre_migration_record(planned=(time(10, 0), time(18, 0)), actual=(time(10, 25), time(17, 50)))
        self.run_backfill()
        record.refresh_from_db()
        self.assertEqual(record.late_minutes, 15)
        self.assertEqual(record.early_leave_minutes, 5)

    def test_an_overnight_shift_is_not_read_as_a_whole_day_early(self):
        # 22:00 -> 02:00 the next morning, left 20 minutes early at 01:40.
        # Without the crosses_midnight offset this would compute as leaving
        # roughly twenty hours early.
        record = self.pre_migration_record(
            planned=(time(22, 0), time(2, 0)), actual=(time(22, 0), time(1, 40)),
            shift_crosses_midnight=True, crosses_midnight=True,
        )
        self.run_backfill()
        record.refresh_from_db()
        self.assertEqual(record.late_minutes, 0)
        self.assertEqual(record.early_leave_minutes, 20)

    def test_arriving_early_and_staying_late_is_never_negative(self):
        record = self.pre_migration_record(planned=(time(10, 0), time(18, 0)), actual=(time(9, 40), time(18, 30)))
        self.run_backfill()
        record.refresh_from_db()
        self.assertEqual((record.late_minutes, record.early_leave_minutes), (0, 0))

    def test_an_absence_is_not_turned_into_an_extreme_lateness(self):
        record = self.pre_migration_record(
            planned=(time(10, 0), time(18, 0)), actual=(None, None), absent=True,
        )
        self.run_backfill()
        record.refresh_from_db()
        self.assertEqual((record.late_minutes, record.early_leave_minutes), (0, 0))

    def test_an_unscheduled_day_has_no_deviation_to_measure(self):
        record = self.pre_migration_record(
            planned=(time(10, 0), time(18, 0)), actual=(time(13, 0), time(23, 0)), with_shift=False,
        )
        self.run_backfill()
        record.refresh_from_db()
        self.assertEqual((record.late_minutes, record.early_leave_minutes), (0, 0))

    def test_an_unfinished_day_is_left_alone(self):
        record = self.pre_migration_record(planned=(time(10, 0), time(18, 0)), actual=(time(10, 30), None))
        self.run_backfill()
        record.refresh_from_db()
        self.assertEqual((record.late_minutes, record.early_leave_minutes), (0, 0))

    def test_the_backfilled_minutes_match_the_runtime_calculation(self):
        """The migration duplicates attendance.exception_minutes by design
        (a migration must not change behaviour when that module does), so
        pin the two together at the moment of writing."""
        record = self.pre_migration_record(planned=(time(17, 0), time(22, 0)), actual=(time(17, 18), time(21, 35)))
        self.run_backfill()
        record.refresh_from_db()
        expected = attendance.exception_minutes(
            record, attendance.shift_for(self.staff_employee, record.work_date),
            attendance.setting_for(self.branch_a),
        )
        self.assertEqual((record.late_minutes, record.early_leave_minutes), expected)

    def test_the_existing_exception_filter_now_finds_the_historical_day(self):
        """The actual point of the backfill: before it, a real late arrival
        is invisible in the manager's default view."""
        self.pre_migration_record(planned=(time(10, 0), time(18, 0)), actual=(time(10, 25), time(18, 0)))
        self.login_as(self.branch_a_user)

        resp = self.client.get('/api/actual-work-records/?exception=true')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(len(self.rows(resp)), 0, 'precondition: late_minutes still 0')

        self.run_backfill()
        rows = self.rows(self.client.get('/api/actual-work-records/?exception=true'))
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]['late_minutes'], 25)

    @staticmethod
    def rows(resp):
        return resp.data['results'] if 'results' in resp.data else resp.data

    def test_nothing_the_wage_engine_reads_is_touched(self):
        record = self.pre_migration_record(planned=(time(10, 0), time(18, 0)), actual=(time(10, 25), time(17, 30)))
        record.actual_break_minutes = 45
        record.save(update_fields=['actual_break_minutes'])
        before = (record.status, record.absent, record.actual_start, record.actual_end,
                  record.actual_break_minutes, record.crosses_midnight)
        self.run_backfill()
        record.refresh_from_db()
        after = (record.status, record.absent, record.actual_start, record.actual_end,
                 record.actual_break_minutes, record.crosses_midnight)
        self.assertEqual(before, after)

    def test_running_it_twice_changes_nothing_further(self):
        record = self.pre_migration_record(planned=(time(10, 0), time(18, 0)), actual=(time(10, 25), time(17, 30)))
        self.run_backfill()
        record.refresh_from_db()
        first = (record.late_minutes, record.early_leave_minutes)
        self.run_backfill()
        record.refresh_from_db()
        self.assertEqual((record.late_minutes, record.early_leave_minutes), first)

    def test_the_reverse_puts_the_columns_back_to_the_schema_default(self):
        record = self.pre_migration_record(planned=(time(10, 0), time(18, 0)), actual=(time(10, 25), time(17, 30)))
        module = self.run_backfill()
        from django.apps import apps as live_apps
        module.clear_exception_minutes(live_apps, None)
        record.refresh_from_db()
        self.assertEqual((record.late_minutes, record.early_leave_minutes), (0, 0))


class GeneratedRecordAuditTests(ApiTestCase):
    """generate_actual_records pre-confirms days straight into payroll, so
    it has to leave the same trail every other attendance write does."""

    def setUp(self):
        super().setUp()
        self.period = SchedulePeriod.objects.create(
            branch=self.branch_a, month=date(2026, 3, 1),
            start_date=date(2026, 3, 1), end_date=date(2026, 3, 31),
            status=SchedulePeriod.Status.PUBLISHED,
        )
        self.second_employee = StaffMember.objects.create(name='DEMO/TEST staff 2', branch=self.branch_a)
        for index, employee in enumerate((self.staff_employee, self.second_employee)):
            Shift.objects.create(
                period=self.period, branch=self.branch_a, employee=employee,
                work_date=date(2026, 3, 10 + index),
                planned_start=time(10, 0), planned_end=time(18, 0),
            )

    def generate(self):
        return self.client.post(f'/api/schedule-periods/{self.period.id}/generate_actual_records/')

    def test_every_generated_record_is_logged(self):
        self.login_as(self.branch_a_user)
        resp = self.generate()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['created'], 2)

        entries = AttendanceChangeLog.objects.filter(source=AttendanceChangeLog.Source.GENERATED)
        self.assertEqual(entries.count(), 2)
        for entry in entries:
            self.assertEqual(entry.changed_by_id, self.branch_a_user.id)
            self.assertIsNone(entry.before, 'the row did not exist before this call')
            self.assertEqual(entry.after['status'], ActualWorkRecord.Status.MANAGER_CONFIRMED)
            self.assertEqual(entry.after['source'], ActualWorkRecord.Source.PLAN)
            self.assertEqual(entry.record.work_date, entry.work_date)

    def test_a_skipped_record_produces_no_entry(self):
        """Running it twice creates nothing, so it must log nothing either —
        an audit trail that reports unchanged rows is noise."""
        self.login_as(self.branch_a_user)
        self.generate()
        before = AttendanceChangeLog.objects.count()
        resp = self.generate()
        self.assertEqual(resp.data['created'], 0)
        self.assertEqual(AttendanceChangeLog.objects.count(), before)

    def test_the_log_entry_is_scoped_to_the_branch_that_owns_the_day(self):
        self.login_as(self.admin)
        self.generate()
        for entry in AttendanceChangeLog.objects.filter(source=AttendanceChangeLog.Source.GENERATED):
            self.assertEqual(entry.branch_id, self.branch_a.id)
