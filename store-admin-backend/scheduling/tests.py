from datetime import date, time
from io import StringIO

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import override_settings
from common.test_utils import ApiTestCase

from branches.models import Branch
from staff.models import StaffMember

from .models import ActualWorkRecord, AvailabilityRequest, SchedulePeriod, Shift
from .services import check_shift


class CheckShiftServiceTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.employee = StaffMember.objects.create(name='测试员工', branch=self.branch_a)
        self.period = SchedulePeriod.objects.create(
            branch=self.branch_a, start_date=date(2026, 1, 5), end_date=date(2026, 1, 11),
        )

    def test_clean_shift_has_no_errors_or_warnings(self):
        hard, soft = check_shift(
            self.employee, self.branch_a, date(2026, 1, 5), time(9, 0), time(17, 0), False, 60, self.period,
        )
        self.assertEqual((hard, soft), ([], []))

    def test_end_before_start_without_midnight_flag_is_hard_error(self):
        hard, soft = check_shift(
            self.employee, self.branch_a, date(2026, 1, 5), time(17, 0), time(9, 0), False, 0, self.period,
        )
        self.assertIn('shift-invalid-time-range', hard)

    def test_break_longer_than_shift_is_hard_error(self):
        hard, soft = check_shift(
            self.employee, self.branch_a, date(2026, 1, 5), time(9, 0), time(17, 0), False, 999, self.period,
        )
        self.assertIn('shift-break-exceeds-duration', hard)

    def test_before_hire_date_is_hard_error(self):
        self.employee.hire_date = date(2026, 2, 1)
        self.employee.save()
        hard, soft = check_shift(
            self.employee, self.branch_a, date(2026, 1, 5), time(9, 0), time(17, 0), False, 0, self.period,
        )
        self.assertIn('shift-before-hire-date', hard)

    def test_after_leave_date_is_hard_error(self):
        self.employee.leave_date = date(2025, 12, 31)
        self.employee.save()
        hard, soft = check_shift(
            self.employee, self.branch_a, date(2026, 1, 5), time(9, 0), time(17, 0), False, 0, self.period,
        )
        self.assertIn('shift-after-leave-date', hard)

    def test_overlapping_shift_same_branch_is_hard_error(self):
        Shift.objects.create(
            period=self.period, branch=self.branch_a, employee=self.employee, work_date=date(2026, 1, 5),
            planned_start=time(8, 0), planned_end=time(12, 0),
        )
        hard, soft = check_shift(
            self.employee, self.branch_a, date(2026, 1, 5), time(11, 0), time(15, 0), False, 0, self.period,
        )
        self.assertIn('shift-overlaps-existing-shift', hard)

    def test_overlapping_shift_other_branch_is_hard_error_with_distinct_code(self):
        Shift.objects.create(
            period=self.period, branch=self.branch_b, employee=self.employee, work_date=date(2026, 1, 5),
            planned_start=time(8, 0), planned_end=time(12, 0),
        )
        hard, soft = check_shift(
            self.employee, self.branch_a, date(2026, 1, 5), time(11, 0), time(15, 0), False, 0, self.period,
        )
        self.assertIn('shift-overlaps-another-branch', hard)

    def test_overlap_check_spans_midnight_crossing_neighbour(self):
        # A shift on the 4th that runs into the 5th must still be caught
        # when proposing a new shift that starts early on the 5th.
        Shift.objects.create(
            period=self.period, branch=self.branch_a, employee=self.employee, work_date=date(2026, 1, 4),
            planned_start=time(22, 0), planned_end=time(2, 0), crosses_midnight=True,
        )
        hard, soft = check_shift(
            self.employee, self.branch_a, date(2026, 1, 5), time(1, 0), time(9, 0), False, 0, self.period,
        )
        self.assertIn('shift-overlaps-existing-shift', hard)

    def test_non_overlapping_shift_is_not_flagged(self):
        Shift.objects.create(
            period=self.period, branch=self.branch_a, employee=self.employee, work_date=date(2026, 1, 5),
            planned_start=time(8, 0), planned_end=time(12, 0),
        )
        hard, soft = check_shift(
            self.employee, self.branch_a, date(2026, 1, 5), time(12, 0), time(16, 0), False, 0, self.period,
        )
        self.assertEqual(hard, [])

    def test_day_off_request_is_soft_warning_not_hard_error(self):
        AvailabilityRequest.objects.create(
            period=self.period, employee=self.employee, work_date=date(2026, 1, 5),
            availability=AvailabilityRequest.Availability.DAY_OFF,
        )
        hard, soft = check_shift(
            self.employee, self.branch_a, date(2026, 1, 5), time(9, 0), time(17, 0), False, 0, self.period,
        )
        self.assertEqual(hard, [])
        self.assertIn('shift-conflicts-with-day-off-request', soft)

    def test_outside_submitted_availability_is_soft_warning(self):
        AvailabilityRequest.objects.create(
            period=self.period, employee=self.employee, work_date=date(2026, 1, 5),
            availability=AvailabilityRequest.Availability.AVAILABLE,
            start_time=time(9, 0), end_time=time(13, 0),
        )
        hard, soft = check_shift(
            self.employee, self.branch_a, date(2026, 1, 5), time(9, 0), time(17, 0), False, 0, self.period,
        )
        self.assertEqual(hard, [])
        self.assertIn('shift-outside-submitted-availability', soft)

    def test_within_submitted_availability_has_no_warning(self):
        AvailabilityRequest.objects.create(
            period=self.period, employee=self.employee, work_date=date(2026, 1, 5),
            availability=AvailabilityRequest.Availability.AVAILABLE,
            start_time=time(9, 0), end_time=time(18, 0),
        )
        hard, soft = check_shift(
            self.employee, self.branch_a, date(2026, 1, 5), time(9, 0), time(17, 0), False, 0, self.period,
        )
        self.assertEqual((hard, soft), ([], []))


class ShiftConsistencyValidationTests(ApiTestCase):
    """A shift must always describe a real employee, at a real branch, in a
    real period — these are hard errors, never overridable."""

    def setUp(self):
        super().setUp()
        self.employee = StaffMember.objects.create(name='测试员工', branch=self.branch_a)
        self.other_branch_employee = StaffMember.objects.create(name='别的分店员工', branch=self.branch_b)
        self.period = SchedulePeriod.objects.create(
            branch=self.branch_a, start_date=date(2026, 1, 5), end_date=date(2026, 1, 11),
        )

    def test_employee_from_another_branch_is_hard_error(self):
        hard, soft = check_shift(
            self.other_branch_employee, self.branch_a, date(2026, 1, 5), time(9, 0), time(17, 0), False, 0,
            self.period,
        )
        self.assertIn('shift-employee-not-in-branch', hard)

    def test_period_from_another_branch_is_hard_error(self):
        other_branch_period = SchedulePeriod.objects.create(
            branch=self.branch_b, start_date=date(2026, 1, 5), end_date=date(2026, 1, 11),
        )
        hard, soft = check_shift(
            self.employee, self.branch_a, date(2026, 1, 5), time(9, 0), time(17, 0), False, 0,
            other_branch_period,
        )
        self.assertIn('shift-period-branch-mismatch', hard)

    def test_work_date_outside_period_range_is_hard_error(self):
        hard, soft = check_shift(
            self.employee, self.branch_a, date(2026, 1, 20), time(9, 0), time(17, 0), False, 0, self.period,
        )
        self.assertIn('shift-date-outside-period', hard)

    def test_consistent_shift_has_no_consistency_errors(self):
        hard, soft = check_shift(
            self.employee, self.branch_a, date(2026, 1, 5), time(9, 0), time(17, 0), False, 0, self.period,
        )
        self.assertNotIn('shift-employee-not-in-branch', hard)
        self.assertNotIn('shift-period-branch-mismatch', hard)
        self.assertNotIn('shift-date-outside-period', hard)

    def test_api_rejects_forged_cross_branch_shift(self):
        """A branch account submitting a shift for another branch's
        employee (or trying to attach its own branch to another branch's
        employee) must be rejected server-side, not just hidden in the UI."""
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/shifts/', {
            'period': self.period.id, 'branch': self.branch_a.id, 'employee': self.other_branch_employee.id,
            'work_date': '2026-01-05', 'planned_start': '09:00', 'planned_end': '17:00',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        body = resp.data if isinstance(resp.data, dict) else {}
        self.assertIn('shift-employee-not-in-branch', str(body))


class BranchScheduleSettingTests(ApiTestCase):
    """Every branch is auto-seeded with the standard 上午/下午/全日 template
    on creation; only admin can change it, branch can only read its own."""

    def test_seeded_defaults_match_spec(self):
        self.login_as(self.admin)
        resp = self.client.get(f'/api/branch-schedule-settings/{self.branch_a.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['morning_start'], '10:30:00')
        self.assertEqual(resp.data['morning_end'], '15:00:00')
        self.assertEqual(resp.data['afternoon_start'], '17:00:00')
        self.assertEqual(resp.data['afternoon_end'], '22:00:00')
        self.assertEqual(resp.data['full_day_start'], '10:30:00')
        self.assertEqual(resp.data['full_day_end'], '22:00:00')
        self.assertEqual(resp.data['full_day_break_start'], '15:00:00')
        self.assertEqual(resp.data['full_day_break_end'], '17:00:00')

    def test_branch_account_can_read_its_own_setting(self):
        self.login_as(self.branch_a_user)
        resp = self.client.get(f'/api/branch-schedule-settings/{self.branch_a.id}/')
        self.assertEqual(resp.status_code, 200)

    def test_branch_account_cannot_read_another_branchs_setting(self):
        self.login_as(self.branch_a_user)
        resp = self.client.get(f'/api/branch-schedule-settings/{self.branch_b.id}/')
        self.assertEqual(resp.status_code, 404)

    def test_branch_account_cannot_change_its_own_setting(self):
        self.login_as(self.branch_a_user)
        resp = self.client.patch(f'/api/branch-schedule-settings/{self.branch_a.id}/', {
            'morning_start': '09:00',
        }, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_admin_can_change_branch_setting(self):
        self.login_as(self.admin)
        resp = self.client.patch(f'/api/branch-schedule-settings/{self.branch_a.id}/', {
            'morning_start': '09:30',
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['morning_start'], '09:30:00')

    def test_staff_account_blocked_entirely(self):
        self.login_as(self.staff_user)
        resp = self.client.get(f'/api/branch-schedule-settings/{self.branch_a.id}/')
        self.assertEqual(resp.status_code, 403)


class MonthlySchedulePeriodTests(ApiTestCase):
    """A period is now created by picking branch+month only — the old
    manual start/end-date entry mode is retired; dates are always
    server-computed for the full calendar month."""

    def test_creating_with_month_computes_full_calendar_month(self):
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/schedule-periods/', {
            'branch': self.branch_a.id, 'month': '2026-06-01',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data['month'], '2026-06-01')
        self.assertEqual(resp.data['start_date'], '2026-06-01')
        self.assertEqual(resp.data['end_date'], '2026-06-30')

    def test_leap_year_february_gets_29_days(self):
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/schedule-periods/', {
            'branch': self.branch_a.id, 'month': '2028-02-01',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data['end_date'], '2028-02-29')

    def test_non_leap_year_february_gets_28_days(self):
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/schedule-periods/', {
            'branch': self.branch_a.id, 'month': '2026-02-01',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data['end_date'], '2026-02-28')

    def test_month_normalizes_any_day_to_the_first(self):
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/schedule-periods/', {
            'branch': self.branch_a.id, 'month': '2026-06-15',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data['month'], '2026-06-01')

    def test_branch_and_month_must_be_unique(self):
        self.login_as(self.branch_a_user)
        self.client.post('/api/schedule-periods/', {'branch': self.branch_a.id, 'month': '2026-06-01'}, format='json')
        resp = self.client.post('/api/schedule-periods/', {'branch': self.branch_a.id, 'month': '2026-06-15'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('schedule-period-month-already-exists', str(resp.data))

    def test_same_month_different_branch_is_allowed(self):
        self.login_as(self.admin)
        self.client.post('/api/schedule-periods/', {'branch': self.branch_a.id, 'month': '2026-06-01'}, format='json')
        resp = self.client.post('/api/schedule-periods/', {'branch': self.branch_b.id, 'month': '2026-06-01'}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_creating_without_month_is_rejected(self):
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/schedule-periods/', {
            'branch': self.branch_a.id, 'start_date': '2026-06-01', 'end_date': '2026-06-07',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_month_cannot_be_changed_after_creation(self):
        self.login_as(self.branch_a_user)
        created = self.client.post('/api/schedule-periods/', {
            'branch': self.branch_a.id, 'month': '2026-06-01',
        }, format='json').data
        resp = self.client.patch(f"/api/schedule-periods/{created['id']}/", {'month': '2026-07-01'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_legacy_period_without_month_still_readable(self):
        legacy = SchedulePeriod.objects.create(
            branch=self.branch_a, start_date=date(2025, 3, 3), end_date=date(2025, 3, 9),
        )
        self.login_as(self.branch_a_user)
        resp = self.client.get(f'/api/schedule-periods/{legacy.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data['month'])
        self.assertEqual(resp.data['start_date'], '2025-03-03')
        self.assertEqual(resp.data['end_date'], '2025-03-09')

    def test_admin_cannot_create_period_for_another_organizations_branch(self):
        from organizations.models import Organization

        other_org = Organization.objects.create(code='other-org-msp', name_zh='另一集团', name_ja='別グループ')
        other_branch = Branch.objects.create(
            id='other-org-branch-msp', organization=other_org, code='b1', name_zh='别店', name_ja='別店',
        )
        self.login_as(self.admin)
        resp = self.client.post('/api/schedule-periods/', {
            'branch': other_branch.id, 'month': '2026-06-01',
        }, format='json')
        self.assertEqual(resp.status_code, 403)


class SchedulePublishVersionTests(ApiTestCase):
    """Publishing a still-collecting/drafting period starts it at its
    existing version (1 by default); re-publishing an already-published
    period (e.g. after editing shifts) bumps the version and refreshes
    published_at/published_by — the signal staff use to notice a change."""

    def test_first_publish_does_not_bump_version(self):
        period = SchedulePeriod.objects.create(branch=self.branch_a, month=date(2026, 6, 1), start_date=date(2026, 6, 1), end_date=date(2026, 6, 30))
        self.login_as(self.branch_a_user)
        resp = self.client.post(f'/api/schedule-periods/{period.id}/publish/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['version'], 1)
        self.assertEqual(resp.data['status'], 'published')

    def test_republish_bumps_version_and_refreshes_publisher(self):
        period = SchedulePeriod.objects.create(branch=self.branch_a, month=date(2026, 6, 1), start_date=date(2026, 6, 1), end_date=date(2026, 6, 30))
        self.login_as(self.branch_a_user)
        self.client.post(f'/api/schedule-periods/{period.id}/publish/')
        resp = self.client.post(f'/api/schedule-periods/{period.id}/publish/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['version'], 2)
        self.assertEqual(resp.data['published_by'], self.branch_a_user.id)

    def test_staff_sees_published_version_and_timestamp(self):
        period = SchedulePeriod.objects.create(branch=self.branch_a, month=date(2026, 6, 1), start_date=date(2026, 6, 1), end_date=date(2026, 6, 30))
        self.login_as(self.branch_a_user)
        self.client.post(f'/api/schedule-periods/{period.id}/publish/')
        self.client.post(f'/api/schedule-periods/{period.id}/publish/')
        self.login_as(self.staff_user)
        resp = self.client.get(f'/api/schedule-periods/{period.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['version'], 2)
        self.assertIsNotNone(resp.data['published_at'])


class GenerateActualRecordsTests(ApiTestCase):
    """generate_actual_records is an internal sync tool the frontend calls
    after every schedule save (draft or published) — it must never require
    the period to be published, and must never clobber a record a manager
    has already started adjusting."""

    def setUp(self):
        super().setUp()
        self.period = SchedulePeriod.objects.create(
            branch=self.branch_a, month=date(2026, 6, 1), start_date=date(2026, 6, 1), end_date=date(2026, 6, 30),
        )
        self.shift = Shift.objects.create(
            period=self.period, branch=self.branch_a, employee=self.staff_employee, work_date=date(2026, 6, 5),
            planned_start=time(10, 30), planned_end=time(22, 0), planned_break_minutes=120,
        )

    def test_works_on_a_still_draft_period(self):
        self.assertNotEqual(self.period.status, SchedulePeriod.Status.PUBLISHED)
        self.login_as(self.branch_a_user)
        resp = self.client.post(f'/api/schedule-periods/{self.period.id}/generate_actual_records/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['created'], 1)
        record = ActualWorkRecord.objects.get(employee=self.staff_employee, work_date=date(2026, 6, 5))
        self.assertEqual(record.actual_start, time(10, 30))
        self.assertEqual(record.actual_end, time(22, 0))

    def test_generated_record_is_pre_confirmed_not_pending(self):
        """A record generated straight from a published shift needs zero
        further manager action before it counts toward wages — see
        WageEndToEndFlowTests.test_freshly_generated_record_counts_toward_wages
        in wages/tests.py for the calculation-side half of this contract."""
        self.login_as(self.branch_a_user)
        resp = self.client.post(f'/api/schedule-periods/{self.period.id}/generate_actual_records/')
        self.assertEqual(resp.status_code, 200, resp.content)
        record = ActualWorkRecord.objects.get(employee=self.staff_employee, work_date=date(2026, 6, 5))
        self.assertEqual(record.status, ActualWorkRecord.Status.MANAGER_CONFIRMED)
        self.assertIsNotNone(record.confirmed_by)
        self.assertIsNotNone(record.confirmed_at)

    def test_second_call_never_duplicates_or_overwrites_existing_record(self):
        self.login_as(self.branch_a_user)
        self.client.post(f'/api/schedule-periods/{self.period.id}/generate_actual_records/')
        record = ActualWorkRecord.objects.get(employee=self.staff_employee, work_date=date(2026, 6, 5))
        # manager already adjusted this one for a late arrival
        record.actual_start = time(11, 0)
        record.adjustment_reason = '迟到'
        record.save()

        resp = self.client.post(f'/api/schedule-periods/{self.period.id}/generate_actual_records/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['created'], 0)
        record.refresh_from_db()
        self.assertEqual(record.actual_start, time(11, 0))
        self.assertEqual(record.adjustment_reason, '迟到')
        self.assertEqual(
            ActualWorkRecord.objects.filter(employee=self.staff_employee, work_date=date(2026, 6, 5)).count(), 1,
        )


class ActualWorkRecordAdjustmentReasonTests(ApiTestCase):
    """The actual work record is meant to only carry a reason when it
    genuinely deviates from what was scheduled — matching the shift exactly
    needs no explanation, but any difference (start/end/break/absent) does."""

    def setUp(self):
        super().setUp()
        self.period = SchedulePeriod.objects.create(
            branch=self.branch_a, month=date(2026, 6, 1), start_date=date(2026, 6, 1), end_date=date(2026, 6, 30),
        )
        self.shift = Shift.objects.create(
            period=self.period, branch=self.branch_a, employee=self.staff_employee, work_date=date(2026, 6, 5),
            planned_start=time(10, 30), planned_end=time(22, 0), planned_break_minutes=120,
        )
        self.record = ActualWorkRecord.objects.create(
            shift=self.shift, branch=self.branch_a, employee=self.staff_employee, work_date=date(2026, 6, 5),
            actual_start=time(10, 30), actual_end=time(22, 0), actual_break_minutes=120,
        )

    def test_matching_shift_exactly_needs_no_reason(self):
        self.login_as(self.branch_a_user)
        resp = self.client.patch(f'/api/actual-work-records/{self.record.id}/', {
            'actual_start': '10:30', 'actual_end': '22:00', 'actual_break_minutes': 120,
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_differing_end_time_without_reason_is_rejected(self):
        self.login_as(self.branch_a_user)
        resp = self.client.patch(f'/api/actual-work-records/{self.record.id}/', {
            'actual_start': '10:30', 'actual_end': '22:30', 'actual_break_minutes': 120,
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('adjustment_reason', str(resp.data))

    def test_differing_end_time_with_reason_is_accepted(self):
        self.login_as(self.branch_a_user)
        resp = self.client.patch(f'/api/actual-work-records/{self.record.id}/', {
            'actual_start': '10:30', 'actual_end': '22:30', 'actual_break_minutes': 120,
            'adjustment_reason': '客人延迟结账',
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_differing_break_minutes_without_reason_is_rejected(self):
        self.login_as(self.branch_a_user)
        resp = self.client.patch(f'/api/actual-work-records/{self.record.id}/', {
            'actual_start': '10:30', 'actual_end': '22:00', 'actual_break_minutes': 90,
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_marking_absent_without_reason_is_rejected(self):
        self.login_as(self.branch_a_user)
        resp = self.client.patch(f'/api/actual-work-records/{self.record.id}/', {'absent': True}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)  # absent bypasses the time-diff check entirely

    def test_walk_in_record_without_shift_needs_no_reason(self):
        walk_in = ActualWorkRecord.objects.create(
            branch=self.branch_a, employee=self.staff_employee, work_date=date(2026, 6, 6),
            actual_start=time(9, 0), actual_end=time(17, 0), actual_break_minutes=30,
        )
        self.login_as(self.branch_a_user)
        resp = self.client.patch(f'/api/actual-work-records/{walk_in.id}/', {
            'actual_start': '09:15', 'actual_end': '17:30',
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_response_exposes_planned_shift_time_for_comparison(self):
        self.login_as(self.branch_a_user)
        resp = self.client.get(f'/api/actual-work-records/{self.record.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['planned_start'], '10:30:00')
        self.assertEqual(resp.data['planned_end'], '22:00:00')
        self.assertEqual(resp.data['planned_break_minutes'], 120)

    def test_walk_in_record_has_null_planned_time(self):
        walk_in = ActualWorkRecord.objects.create(
            branch=self.branch_a, employee=self.staff_employee, work_date=date(2026, 6, 7),
            actual_start=time(9, 0), actual_end=time(17, 0), actual_break_minutes=30,
        )
        self.login_as(self.branch_a_user)
        resp = self.client.get(f'/api/actual-work-records/{walk_in.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data['planned_start'])


class ActualWorkRecordDateRangeFilterTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        for day in (1, 15, 28):
            ActualWorkRecord.objects.create(
                branch=self.branch_a, employee=self.staff_employee, work_date=date(2026, 6, day),
                actual_start=time(9, 0), actual_end=time(17, 0), actual_break_minutes=30,
            )
        ActualWorkRecord.objects.create(
            branch=self.branch_a, employee=self.staff_employee, work_date=date(2026, 7, 1),
            actual_start=time(9, 0), actual_end=time(17, 0), actual_break_minutes=30,
        )

    def test_date_range_scopes_to_one_month(self):
        self.login_as(self.branch_a_user)
        resp = self.client.get('/api/actual-work-records/?date_from=2026-06-01&date_to=2026-06-30')
        self.assertEqual(resp.status_code, 200)
        dates = {row['work_date'] for row in resp.data}
        self.assertEqual(dates, {'2026-06-01', '2026-06-15', '2026-06-28'})


class ActualWorkRecordConsistencyTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.period = SchedulePeriod.objects.create(
            branch=self.branch_a, month=date(2026, 9, 1),
            start_date=date(2026, 9, 1), end_date=date(2026, 9, 30),
        )
        self.shift = Shift.objects.create(
            period=self.period, branch=self.branch_a, employee=self.staff_employee,
            work_date=date(2026, 9, 2), planned_start=time(10, 30), planned_end=time(22),
            planned_break_minutes=120,
        )

    def test_shift_employee_branch_and_date_must_match(self):
        other = StaffMember.objects.create(name='other branch', branch=self.branch_b)
        self.login_as(self.admin)
        response = self.client.post('/api/actual-work-records/', {
            'shift': self.shift.id, 'branch': self.branch_a.id, 'employee': other.id,
            'work_date': '2026-09-03', 'actual_start': '10:30', 'actual_end': '22:00',
            'actual_break_minutes': 120,
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ActualWorkRecord.objects.count(), 0)

    def test_identity_fields_are_immutable_on_patch(self):
        record = ActualWorkRecord.objects.create(
            shift=self.shift, branch=self.branch_a, employee=self.staff_employee,
            work_date=date(2026, 9, 2), actual_start=time(10, 30), actual_end=time(22),
            actual_break_minutes=120,
        )
        other = StaffMember.objects.create(name='other', branch=self.branch_a)
        self.login_as(self.admin)
        response = self.client.patch(f'/api/actual-work-records/{record.id}/', {
            'employee': other.id,
        }, format='json')
        self.assertEqual(response.status_code, 400)
        record.refresh_from_db()
        self.assertEqual(record.employee, self.staff_employee)

    def test_actual_times_and_break_are_validated(self):
        self.login_as(self.branch_a_user)
        base = {
            'branch': self.branch_a.id, 'employee': self.staff_employee.id,
            'work_date': '2026-09-03',
        }
        self.assertEqual(self.client.post('/api/actual-work-records/', base, format='json').status_code, 400)
        self.assertEqual(self.client.post('/api/actual-work-records/', {
            **base, 'actual_start': '18:00', 'actual_end': '10:00', 'actual_break_minutes': 0,
        }, format='json').status_code, 400)
        self.assertEqual(self.client.post('/api/actual-work-records/', {
            **base, 'actual_start': '10:00', 'actual_end': '11:00', 'actual_break_minutes': 61,
        }, format='json').status_code, 400)


class ScheduleWageDemoSeedTests(ApiTestCase):
    @override_settings(DEBUG=True)
    def test_command_is_idempotent(self):
        self.branch_a.code = 'shinsaibashi'
        self.branch_a.save(update_fields=['code'])
        out = StringIO()
        call_command('seed_schedule_wage_demo', stdout=out)
        counts = {
            'staff': StaffMember.objects.filter(name__startswith='排班演示・').count(),
            'shifts': Shift.objects.filter(period__branch=self.branch_a, period__month=date(2026, 8, 1)).count(),
            'actual': ActualWorkRecord.objects.filter(
                branch=self.branch_a, employee__name__startswith='排班演示・', work_date__month=8,
            ).count(),
        }
        call_command('seed_schedule_wage_demo', stdout=out)
        self.assertEqual(counts['staff'], 4)
        self.assertEqual(StaffMember.objects.filter(name__startswith='排班演示・').count(), counts['staff'])
        self.assertEqual(Shift.objects.filter(period__branch=self.branch_a, period__month=date(2026, 8, 1)).count(), counts['shifts'])
        self.assertEqual(ActualWorkRecord.objects.filter(
            branch=self.branch_a, employee__name__startswith='排班演示・', work_date__month=8,
        ).count(), counts['actual'])


class SchedulePeriodDatabaseConstraintTests(ApiTestCase):
    def test_database_rejects_duplicate_non_null_month_but_allows_legacy_null(self):
        SchedulePeriod.objects.create(
            branch=self.branch_a, month=date(2026, 10, 1),
            start_date=date(2026, 10, 1), end_date=date(2026, 10, 31),
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            SchedulePeriod.objects.create(
                branch=self.branch_a, month=date(2026, 10, 1),
                start_date=date(2026, 10, 1), end_date=date(2026, 10, 31),
            )
        SchedulePeriod.objects.create(
            branch=self.branch_a, month=None,
            start_date=date(2025, 1, 1), end_date=date(2025, 1, 2),
        )
        SchedulePeriod.objects.create(
            branch=self.branch_a, month=None,
            start_date=date(2025, 2, 1), end_date=date(2025, 2, 2),
        )
