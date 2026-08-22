from datetime import date, time
from decimal import Decimal

from django.test import SimpleTestCase

from common.test_utils import ApiTestCase
from staff.models import StaffMember

from .calculation import classify_minutes, round_yen, split_overtime_within_week
from .models import WageRule


class ClassifyMinutesTests(SimpleTestCase):
    def test_plain_daytime_shift_has_no_night_minutes(self):
        total, night = classify_minutes(time(9, 0), time(17, 0), False, 0)
        self.assertEqual(total, 480)
        self.assertEqual(night, 0)

    def test_evening_shift_partially_overlaps_night(self):
        # 20:00-23:00 overlaps [22:00, 24:00) by exactly 1 hour.
        total, night = classify_minutes(time(20, 0), time(23, 0), False, 0)
        self.assertEqual(total, 180)
        self.assertEqual(night, 60)

    def test_shift_entirely_inside_night_window_crossing_midnight(self):
        total, night = classify_minutes(time(23, 0), time(2, 0), True, 0)
        self.assertEqual(total, 180)
        self.assertEqual(night, 180)

    def test_early_morning_shift_overlaps_night_tail(self):
        # 03:00-06:00: 03:00-05:00 is night, 05:00-06:00 is not.
        total, night = classify_minutes(time(3, 0), time(6, 0), False, 0)
        self.assertEqual(total, 180)
        self.assertEqual(night, 120)

    def test_break_is_deducted_from_regular_portion_first(self):
        # 20:00-06:00 crossing midnight: 600 raw minutes, 420 of them
        # night (22:00-05:00). A 60-minute break should come out of the
        # 180 regular minutes, leaving night untouched.
        total, night = classify_minutes(time(20, 0), time(6, 0), True, 60)
        self.assertEqual(total, 540)
        self.assertEqual(night, 420)

    def test_break_spills_into_night_once_regular_portion_exhausted(self):
        # Same shift, but a break larger than the 180 regular minutes
        # available — the remainder must come out of night minutes too.
        total, night = classify_minutes(time(20, 0), time(6, 0), True, 240)
        self.assertEqual(total, 360)
        self.assertEqual(night, 360)  # 420 - (240 - 180) = 360

    def test_zero_length_or_inverted_shift_is_zero(self):
        total, night = classify_minutes(time(10, 0), time(10, 0), False, 0)
        self.assertEqual((total, night), (0, 0))


class SplitOvertimeWithinWeekTests(SimpleTestCase):
    def test_single_long_day_only_gets_daily_overtime(self):
        result = split_overtime_within_week([(date(2026, 1, 5), 540)])  # 9h
        self.assertEqual(result[date(2026, 1, 5)], 60)

    def test_five_nine_hour_days_hit_exactly_40h_regular_no_weekly_excess(self):
        days = [(date(2026, 1, 5 + i), 540) for i in range(5)]
        result = split_overtime_within_week(days)
        # Each day: 60 min daily OT, 480 min regular; 5*480 = 2400 = 40h
        # exactly, so nothing spills into weekly overtime.
        for d, _ in days:
            self.assertEqual(result[d], 60)

    def test_six_eight_hour_days_last_day_becomes_all_weekly_overtime(self):
        days = [(date(2026, 1, 5 + i), 480) for i in range(6)]  # no daily OT anywhere
        result = split_overtime_within_week(days)
        for d, _ in days[:5]:
            self.assertEqual(result[d], 0)
        self.assertEqual(result[days[5][0]], 480)

    def test_overtime_minute_never_double_counted(self):
        # A day long enough to trigger both daily AND weekly overtime on
        # its own must not have those minutes counted twice.
        days = [
            (date(2026, 1, 5), 480), (date(2026, 1, 6), 480), (date(2026, 1, 7), 480),
            (date(2026, 1, 8), 480), (date(2026, 1, 9), 480),  # 2400 regular so far
            (date(2026, 1, 10), 600),  # 10h: 120 daily OT + all 480 regular becomes weekly OT
        ]
        result = split_overtime_within_week(days)
        last_day_total = days[-1][1]
        self.assertEqual(result[days[-1][0]], 600)  # 120 daily + 480 weekly = 600, i.e. the whole day
        self.assertLessEqual(result[days[-1][0]], last_day_total)


class RoundYenTests(SimpleTestCase):
    def test_half_rounds_up(self):
        self.assertEqual(round_yen(Decimal('100.5')), Decimal('101'))
        self.assertEqual(round_yen(Decimal('100.4')), Decimal('100'))
        self.assertEqual(round_yen(Decimal('100.49999')), Decimal('100'))


class WageRuleOverlapTests(ApiTestCase):
    def test_overlapping_period_rejected(self):
        WageRule.objects.create(
            employee=self.staff_employee, effective_from=date(2026, 1, 1), effective_to=date(2026, 6, 30),
            hourly_rate=1200,
        )
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/wage-rules/', {
            'employee': self.staff_employee.id, 'effective_from': '2026-4-01', 'hourly_rate': 1300,
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_adjacent_non_overlapping_period_accepted(self):
        WageRule.objects.create(
            employee=self.staff_employee, effective_from=date(2026, 1, 1), effective_to=date(2026, 6, 30),
            hourly_rate=1200,
        )
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/wage-rules/', {
            'employee': self.staff_employee.id, 'effective_from': '2026-07-01', 'hourly_rate': 1300,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_open_ended_rule_blocks_any_later_period(self):
        WageRule.objects.create(
            employee=self.staff_employee, effective_from=date(2026, 1, 1), effective_to=None, hourly_rate=1200,
        )
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/wage-rules/', {
            'employee': self.staff_employee.id, 'effective_from': '2030-01-01', 'hourly_rate': 1300,
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_branch_cannot_create_rule_for_other_branchs_employee(self):
        other_employee = StaffMember.objects.create(name='其他分店员工', branch=self.branch_b)
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/wage-rules/', {
            'employee': other_employee.id, 'effective_from': '2026-01-01', 'hourly_rate': 1200,
        }, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_staff_role_cannot_reach_wage_rules_at_all(self):
        self.login_as(self.staff_user)
        resp = self.client.get('/api/wage-rules/')
        self.assertEqual(resp.status_code, 403)


class WageEndToEndFlowTests(ApiTestCase):
    """Mirrors the full user-facing flow end to end: staff submits
    availability -> branch creates and publishes a shift -> branch
    generates and confirms the actual attendance -> admin confirms and
    locks the wage month -> staff reads (read-only) its own result."""

    def _setup_period_and_rule(self):
        from scheduling.models import SchedulePeriod

        WageRule.objects.create(
            employee=self.staff_employee, effective_from=date(2026, 1, 1), hourly_rate=1200,
            night_premium_rate=Decimal('0.25'), overtime_premium_rate=Decimal('0.25'),
            transportation_type=WageRule.TransportationType.PER_ATTENDANCE, transportation_amount=500,
        )
        return SchedulePeriod.objects.create(
            branch=self.branch_a, start_date=date(2026, 1, 5), end_date=date(2026, 1, 11),
        )

    def test_full_flow(self):
        period = self._setup_period_and_rule()

        # 1. staff submits a week of availability
        self.login_as(self.staff_user)
        resp = self.client.post('/api/availability-requests/', {
            'period': period.id, 'employee': self.staff_employee.id, 'work_date': '2026-01-05',
            'availability': 'available', 'start_time': '09:00', 'end_time': '18:00',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)

        # staff cannot submit availability for someone else
        other_employee = StaffMember.objects.create(name='别人', branch=self.branch_a)
        resp = self.client.post('/api/availability-requests/', {
            'period': period.id, 'employee': other_employee.id, 'work_date': '2026-01-05',
            'availability': 'available', 'start_time': '09:00', 'end_time': '18:00',
        }, format='json')
        self.assertEqual(resp.status_code, 403)

        # 2. branch creates and publishes a shift within the submitted availability
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/shifts/', {
            'period': period.id, 'branch': self.branch_a.id, 'employee': self.staff_employee.id,
            'work_date': '2026-01-05', 'planned_start': '09:00', 'planned_end': '18:00',
            'planned_break_minutes': 60,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)

        # staff cannot see the shift before the period is published
        self.login_as(self.staff_user)
        self.assertEqual(len(self.client.get('/api/shifts/').data), 0)

        self.login_as(self.branch_a_user)
        resp = self.client.post(f'/api/schedule-periods/{period.id}/publish/')
        self.assertEqual(resp.status_code, 200)

        # staff can now see its own published shift
        self.login_as(self.staff_user)
        shifts = self.client.get('/api/shifts/').data
        self.assertEqual(len(shifts), 1)

        # 3. branch generates actual work records (idempotent) and confirms
        self.login_as(self.branch_a_user)
        resp = self.client.post(f'/api/schedule-periods/{period.id}/generate_actual_records/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['created'], 1)
        resp_again = self.client.post(f'/api/schedule-periods/{period.id}/generate_actual_records/')
        self.assertEqual(resp_again.data['created'], 0)  # idempotent — no duplicate

        record = self.client.get('/api/actual-work-records/').data[0]
        resp = self.client.patch(f'/api/actual-work-records/{record["id"]}/', {
            'actual_start': '09:00', 'actual_end': '18:00', 'actual_break_minutes': 60,
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['status'], 'manager_confirmed')

        # 4. admin generates, confirms, and locks the wage month
        self.login_as(self.admin)
        resp = self.client.post('/api/wage-monthly-closings/', {
            'branch': self.branch_a.id, 'month': '2026-01-01',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        closing_id = resp.data['id']

        resp = self.client.post(f'/api/wage-monthly-closings/{closing_id}/generate/')
        self.assertEqual(resp.status_code, 200, resp.content)
        results = resp.data['employee_results']
        self.assertEqual(len(results), 1)
        # 8h worked, 1h break -> 8h paid; no night/overtime/holiday.
        # base = 8 * 1200 = 9600; transportation (per-attendance) = 500.
        self.assertEqual(Decimal(results[0]['base_amount']), Decimal('9600'))
        self.assertEqual(Decimal(results[0]['estimated_total']), Decimal('10100'))

        resp = self.client.post(f'/api/wage-monthly-closings/{closing_id}/confirm/')
        self.assertEqual(resp.status_code, 200, resp.content)
        resp = self.client.post(f'/api/wage-monthly-closings/{closing_id}/lock/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['status'], 'locked')

        # 5. staff reads its own (read-only) wage result — and only its own
        self.login_as(self.staff_user)
        resp = self.client.get('/api/wage-employee-results/')
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(Decimal(resp.data[0]['estimated_total']), Decimal('10100'))
        write_resp = self.client.patch(f'/api/wage-employee-results/{resp.data[0]["id"]}/', {
            'manual_addition': 999999,
        }, format='json')
        self.assertEqual(write_resp.status_code, 403)

        # locked month can no longer be regenerated
        self.login_as(self.admin)
        resp = self.client.post(f'/api/wage-monthly-closings/{closing_id}/generate/')
        self.assertEqual(resp.status_code, 400)

    def test_branch_cannot_see_other_branchs_wage_results(self):
        self._setup_period_and_rule()
        self.login_as(self.branch_b_user)
        resp = self.client.get('/api/wage-employee-results/')
        self.assertEqual(resp.data, [])

    def test_confirm_blocked_when_wage_rule_missing(self):
        from scheduling.models import ActualWorkRecord

        # No WageRule created this time.
        ActualWorkRecord.objects.create(
            branch=self.branch_a, employee=self.staff_employee, work_date=date(2026, 2, 2),
            actual_start=time(9, 0), actual_end=time(17, 0), actual_break_minutes=60,
            status='manager_confirmed',
        )
        self.login_as(self.admin)
        resp = self.client.post('/api/wage-monthly-closings/', {
            'branch': self.branch_a.id, 'month': '2026-02-01',
        }, format='json')
        closing_id = resp.data['id']
        self.client.post(f'/api/wage-monthly-closings/{closing_id}/generate/')
        resp = self.client.post(f'/api/wage-monthly-closings/{closing_id}/confirm/')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['code'], 'missing-wage-rule')
        self.assertEqual(len(resp.data['missing']), 1)

    def test_unlock_requires_reason(self):
        period = self._setup_period_and_rule()
        self.login_as(self.admin)
        resp = self.client.post('/api/wage-monthly-closings/', {
            'branch': self.branch_a.id, 'month': '2026-01-01',
        }, format='json')
        closing_id = resp.data['id']
        self.client.post(f'/api/wage-monthly-closings/{closing_id}/generate/')
        self.client.post(f'/api/wage-monthly-closings/{closing_id}/confirm/')
        self.client.post(f'/api/wage-monthly-closings/{closing_id}/lock/')

        resp = self.client.post(f'/api/wage-monthly-closings/{closing_id}/unlock/', {}, format='json')
        self.assertEqual(resp.status_code, 400)

        resp = self.client.post(
            f'/api/wage-monthly-closings/{closing_id}/unlock/', {'reason': '录入错误需要更正'}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['status'], 'draft')


class WageV2SimpleTests(ApiTestCase):
    """v2_simple: base pay = actual minutes / 60 * hourly rate, no night/
    overtime/holiday premiums; regular_monthly tracks hours but never gets
    a wage amount; bonus/transportation-override/calculation-period all
    survive a re-generate."""

    def _confirmed_record(self, work_date=date(2026, 3, 5), start=time(9, 0), end=time(17, 0), break_min=60):
        from scheduling.models import ActualWorkRecord
        return ActualWorkRecord.objects.create(
            branch=self.branch_a, employee=self.staff_employee, work_date=work_date,
            actual_start=start, actual_end=end, actual_break_minutes=break_min,
            status=ActualWorkRecord.Status.MANAGER_CONFIRMED,
        )

    def _closing_for(self, month='2026-03-01'):
        resp = self.client.post(
            '/api/wage-monthly-closings/', {'branch': self.branch_a.id, 'month': month}, format='json',
        )
        return resp.data['id']

    def test_no_night_overtime_holiday_premiums_even_past_22h(self):
        # 20:00-23:00 crosses into the night window (22:00-05:00), and a
        # v1 rule would have added a night premium — v2_simple must not.
        WageRule.objects.create(employee=self.staff_employee, effective_from=date(2026, 3, 1), hourly_rate=1000)
        self._confirmed_record(start=time(20, 0), end=time(23, 0), break_min=0)
        self.login_as(self.admin)
        closing_id = self._closing_for()
        resp = self.client.post(f'/api/wage-monthly-closings/{closing_id}/generate/')
        result = resp.data['employee_results'][0]
        self.assertEqual(Decimal(result['night_premium']), Decimal('0'))
        self.assertEqual(Decimal(result['overtime_premium']), Decimal('0'))
        self.assertEqual(Decimal(result['holiday_premium']), Decimal('0'))
        self.assertEqual(Decimal(result['base_amount']), Decimal('3000'))  # 3h * 1000

    def test_regular_monthly_is_not_in_simple_payroll_table(self):
        self.staff_employee.employment_type = StaffMember.EmploymentType.REGULAR_MONTHLY
        self.staff_employee.save()
        self._confirmed_record()
        self.login_as(self.admin)
        closing_id = self._closing_for()
        resp = self.client.post(f'/api/wage-monthly-closings/{closing_id}/generate/')
        self.assertEqual(resp.data['employee_results'], [])

    def test_bonus_requires_note_when_nonzero(self):
        WageRule.objects.create(employee=self.staff_employee, effective_from=date(2026, 3, 1), hourly_rate=1000)
        self._confirmed_record()
        self.login_as(self.admin)
        closing_id = self._closing_for()
        resp = self.client.post(f'/api/wage-monthly-closings/{closing_id}/generate/')
        result_id = resp.data['employee_results'][0]['id']

        resp = self.client.patch(f'/api/wage-employee-results/{result_id}/', {'bonus_amount': 5000}, format='json')
        self.assertEqual(resp.status_code, 400)

        resp = self.client.patch(f'/api/wage-employee-results/{result_id}/', {
            'bonus_amount': 5000, 'bonus_note': '全勤奖',
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(Decimal(resp.data['estimated_total']), Decimal('5000') + Decimal(resp.data['base_amount']))
        self.assertIsNotNone(resp.data['bonus_updated_by'])
        self.assertIsNotNone(resp.data['bonus_updated_at'])

    def test_transportation_override_replaces_rule_default(self):
        WageRule.objects.create(
            employee=self.staff_employee, effective_from=date(2026, 3, 1), hourly_rate=1000,
            transportation_type=WageRule.TransportationType.PER_ATTENDANCE, transportation_amount=300,
        )
        self._confirmed_record()
        self.login_as(self.admin)
        closing_id = self._closing_for()
        resp = self.client.post(f'/api/wage-monthly-closings/{closing_id}/generate/')
        result = resp.data['employee_results'][0]
        self.assertEqual(Decimal(result['transportation_amount']), Decimal('300'))  # rule default

        resp = self.client.patch(f'/api/wage-employee-results/{result["id"]}/', {
            'monthly_transportation_override': 800, 'transportation_override_reason': '本月改坐出租车',
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(Decimal(resp.data['transportation_amount']), Decimal('800'))

        # regenerating must not discard the override
        resp = self.client.post(f'/api/wage-monthly-closings/{closing_id}/generate/')
        result = resp.data['employee_results'][0]
        self.assertEqual(Decimal(result['transportation_amount']), Decimal('800'))

        # clearing the override reverts to the rule default immediately —
        # no regenerate needed
        resp = self.client.patch(f'/api/wage-employee-results/{result["id"]}/', {
            'monthly_transportation_override': None,
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(Decimal(resp.data['transportation_amount']), Decimal('300'))

    def test_bonus_and_override_survive_regenerate_after_new_attendance(self):
        WageRule.objects.create(employee=self.staff_employee, effective_from=date(2026, 3, 1), hourly_rate=1000)
        self._confirmed_record(work_date=date(2026, 3, 5))
        self.login_as(self.admin)
        closing_id = self._closing_for()
        resp = self.client.post(f'/api/wage-monthly-closings/{closing_id}/generate/')
        result_id = resp.data['employee_results'][0]['id']
        self.client.patch(f'/api/wage-employee-results/{result_id}/', {
            'bonus_amount': 2000, 'bonus_note': '奖金',
        }, format='json')

        # a second attendance day gets confirmed later, then generate re-runs
        self._confirmed_record(work_date=date(2026, 3, 6))
        resp = self.client.post(f'/api/wage-monthly-closings/{closing_id}/generate/')
        result = resp.data['employee_results'][0]
        self.assertEqual(result['attendance_days'], 2)
        self.assertEqual(Decimal(result['base_amount']), Decimal('14000'))  # 2 * 7h * 1000
        self.assertEqual(Decimal(result['bonus_amount']), Decimal('2000'))  # preserved
        self.assertEqual(Decimal(result['estimated_total']), Decimal('16000'))

    def test_result_resets_to_zero_hours_when_attendance_unconfirmed(self):
        WageRule.objects.create(employee=self.staff_employee, effective_from=date(2026, 3, 1), hourly_rate=1000)
        record = self._confirmed_record()
        self.login_as(self.admin)
        closing_id = self._closing_for()
        self.client.post(f'/api/wage-monthly-closings/{closing_id}/generate/')

        record.status = 'pending'
        record.save()
        resp = self.client.post(f'/api/wage-monthly-closings/{closing_id}/generate/')
        result = resp.data['employee_results'][0]
        self.assertEqual(result['attendance_days'], 0)
        self.assertEqual(Decimal(result['base_amount']), Decimal('0'))

    def test_calculation_period_override_restricts_included_days(self):
        WageRule.objects.create(employee=self.staff_employee, effective_from=date(2026, 3, 1), hourly_rate=1000)
        self._confirmed_record(work_date=date(2026, 3, 5))
        self._confirmed_record(work_date=date(2026, 3, 20))
        self.login_as(self.admin)
        closing_id = self._closing_for()
        resp = self.client.post(f'/api/wage-monthly-closings/{closing_id}/generate/')
        result_id = resp.data['employee_results'][0]['id']
        self.assertEqual(resp.data['employee_results'][0]['attendance_days'], 2)

        resp = self.client.patch(f'/api/wage-employee-results/{result_id}/', {
            'calculation_period_start': '2026-03-01', 'calculation_period_end': '2026-03-10',
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['attendance_days'], 1)  # recalculated immediately
        self.assertEqual(Decimal(resp.data['base_amount']), Decimal('7000'))

    def test_calculation_period_must_be_within_closing_month(self):
        WageRule.objects.create(employee=self.staff_employee, effective_from=date(2026, 3, 1), hourly_rate=1000)
        self._confirmed_record()
        self.login_as(self.admin)
        closing_id = self._closing_for()
        resp = self.client.post(f'/api/wage-monthly-closings/{closing_id}/generate/')
        result_id = resp.data['employee_results'][0]['id']

        resp = self.client.patch(f'/api/wage-employee-results/{result_id}/', {
            'calculation_period_start': '2026-02-01', 'calculation_period_end': '2026-03-10',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_mid_month_leave_date_caps_default_calculation_end(self):
        self.staff_employee.leave_date = date(2026, 3, 15)
        self.staff_employee.save()
        WageRule.objects.create(employee=self.staff_employee, effective_from=date(2026, 3, 1), hourly_rate=1000)
        self._confirmed_record(work_date=date(2026, 3, 10))
        self._confirmed_record(work_date=date(2026, 3, 25))  # after leave_date — should be excluded by default
        self.login_as(self.admin)
        closing_id = self._closing_for()
        resp = self.client.post(f'/api/wage-monthly-closings/{closing_id}/generate/')
        result = resp.data['employee_results'][0]
        self.assertEqual(result['attendance_days'], 1)


class PendingActualRecordsExcludedFromWageTests(ApiTestCase):
    """generate_wage_results must never read a `pending` ActualWorkRecord —
    only manager_confirmed/admin_locked attendance counts toward pay."""

    def test_pending_only_record_produces_zero_result_for_visible_employee(self):
        from scheduling.models import ActualWorkRecord

        WageRule.objects.create(employee=self.staff_employee, effective_from=date(2026, 3, 1), hourly_rate=1000)
        ActualWorkRecord.objects.create(
            branch=self.branch_a, employee=self.staff_employee, work_date=date(2026, 3, 5),
            actual_start=time(9, 0), actual_end=time(17, 0), actual_break_minutes=0,
            status=ActualWorkRecord.Status.PENDING,
        )
        self.login_as(self.admin)
        closing_id = self.client.post(
            '/api/wage-monthly-closings/', {'branch': self.branch_a.id, 'month': '2026-03-01'}, format='json',
        ).data['id']
        self.client.post(f'/api/wage-monthly-closings/{closing_id}/generate/')
        results = self.client.get(f'/api/wage-employee-results/?closing={closing_id}').data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['attendance_days'], 0)
        self.assertEqual(Decimal(results[0]['base_amount']), Decimal('0'))

    def test_confirmed_day_included_pending_day_excluded(self):
        from scheduling.models import ActualWorkRecord

        WageRule.objects.create(employee=self.staff_employee, effective_from=date(2026, 3, 1), hourly_rate=1000)
        ActualWorkRecord.objects.create(
            branch=self.branch_a, employee=self.staff_employee, work_date=date(2026, 3, 5),
            actual_start=time(9, 0), actual_end=time(17, 0), actual_break_minutes=0,
            status=ActualWorkRecord.Status.MANAGER_CONFIRMED,
        )
        ActualWorkRecord.objects.create(
            branch=self.branch_a, employee=self.staff_employee, work_date=date(2026, 3, 6),
            actual_start=time(9, 0), actual_end=time(17, 0), actual_break_minutes=0,
            status=ActualWorkRecord.Status.PENDING,
        )
        self.login_as(self.admin)
        closing_id = self.client.post(
            '/api/wage-monthly-closings/', {'branch': self.branch_a.id, 'month': '2026-03-01'}, format='json',
        ).data['id']
        self.client.post(f'/api/wage-monthly-closings/{closing_id}/generate/')
        results = self.client.get(f'/api/wage-employee-results/?closing={closing_id}').data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['attendance_days'], 1)

    def test_admin_locked_record_is_included(self):
        from scheduling.models import ActualWorkRecord

        WageRule.objects.create(employee=self.staff_employee, effective_from=date(2026, 3, 1), hourly_rate=1000)
        ActualWorkRecord.objects.create(
            branch=self.branch_a, employee=self.staff_employee, work_date=date(2026, 3, 5),
            actual_start=time(9, 0), actual_end=time(17, 0), actual_break_minutes=0,
            status=ActualWorkRecord.Status.ADMIN_LOCKED,
        )
        self.login_as(self.admin)
        closing_id = self.client.post(
            '/api/wage-monthly-closings/', {'branch': self.branch_a.id, 'month': '2026-03-01'}, format='json',
        ).data['id']
        self.client.post(f'/api/wage-monthly-closings/{closing_id}/generate/')
        results = self.client.get(f'/api/wage-employee-results/?closing={closing_id}').data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['attendance_days'], 1)

    def test_freshly_generated_record_counts_toward_wages(self):
        """The other half of the contract in
        scheduling/tests.py:GenerateActualRecordsTests.test_generated_record_is_pre_confirmed_not_pending —
        a manager who publishes a shift and runs generate_actual_records,
        without touching the resulting record at all, must see it counted
        in wages immediately. No separate per-record confirm step."""
        from scheduling.models import ActualWorkRecord, SchedulePeriod, Shift

        WageRule.objects.create(employee=self.staff_employee, effective_from=date(2026, 3, 1), hourly_rate=1000)
        period = SchedulePeriod.objects.create(
            branch=self.branch_a, month=date(2026, 3, 1), start_date=date(2026, 3, 1), end_date=date(2026, 3, 31),
        )
        Shift.objects.create(
            period=period, branch=self.branch_a, employee=self.staff_employee, work_date=date(2026, 3, 5),
            planned_start=time(9, 0), planned_end=time(17, 0), planned_break_minutes=0,
        )
        self.login_as(self.admin)
        self.client.post(f'/api/schedule-periods/{period.id}/generate_actual_records/')
        record = ActualWorkRecord.objects.get(employee=self.staff_employee, work_date=date(2026, 3, 5))
        self.assertEqual(record.status, ActualWorkRecord.Status.MANAGER_CONFIRMED)

        closing_id = self.client.post(
            '/api/wage-monthly-closings/', {'branch': self.branch_a.id, 'month': '2026-03-01'}, format='json',
        ).data['id']
        self.client.post(f'/api/wage-monthly-closings/{closing_id}/generate/')
        results = self.client.get(f'/api/wage-employee-results/?closing={closing_id}').data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['attendance_days'], 1)
        self.assertEqual(Decimal(results[0]['base_amount']), Decimal('8000'))


class ConfirmRequiresFreshCalculationTests(ApiTestCase):
    """confirm must refuse to run on a closing that was never generated, or
    whose ActualWorkRecord/WageRule inputs changed after the last generate
    — never let a manager confirm stale or empty numbers."""

    def _setup_confirmed_record(self):
        from scheduling.models import ActualWorkRecord

        WageRule.objects.create(employee=self.staff_employee, effective_from=date(2026, 4, 1), hourly_rate=1000)
        return ActualWorkRecord.objects.create(
            branch=self.branch_a, employee=self.staff_employee, work_date=date(2026, 4, 5),
            actual_start=time(9, 0), actual_end=time(17, 0), actual_break_minutes=0,
            status=ActualWorkRecord.Status.MANAGER_CONFIRMED,
        )

    def test_confirm_blocked_when_never_generated(self):
        self._setup_confirmed_record()
        self.login_as(self.admin)
        closing_id = self.client.post(
            '/api/wage-monthly-closings/', {'branch': self.branch_a.id, 'month': '2026-04-01'}, format='json',
        ).data['id']
        resp = self.client.post(f'/api/wage-monthly-closings/{closing_id}/confirm/')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['code'], 'not-generated')

    def test_confirm_blocked_when_actual_record_edited_after_generate(self):
        record = self._setup_confirmed_record()
        self.login_as(self.admin)
        closing_id = self.client.post(
            '/api/wage-monthly-closings/', {'branch': self.branch_a.id, 'month': '2026-04-01'}, format='json',
        ).data['id']
        self.client.post(f'/api/wage-monthly-closings/{closing_id}/generate/')

        record.actual_end = time(18, 0)
        record.save()

        resp = self.client.post(f'/api/wage-monthly-closings/{closing_id}/confirm/')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['code'], 'stale-actual-records')

    def test_confirm_blocked_when_wage_rule_edited_after_generate(self):
        self._setup_confirmed_record()
        self.login_as(self.admin)
        closing_id = self.client.post(
            '/api/wage-monthly-closings/', {'branch': self.branch_a.id, 'month': '2026-04-01'}, format='json',
        ).data['id']
        self.client.post(f'/api/wage-monthly-closings/{closing_id}/generate/')

        rule = WageRule.objects.get(employee=self.staff_employee)
        rule.hourly_rate = 1100
        rule.save()

        resp = self.client.post(f'/api/wage-monthly-closings/{closing_id}/confirm/')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['code'], 'stale-wage-rule')

    def test_confirm_succeeds_immediately_after_generate(self):
        self._setup_confirmed_record()
        self.login_as(self.admin)
        closing_id = self.client.post(
            '/api/wage-monthly-closings/', {'branch': self.branch_a.id, 'month': '2026-04-01'}, format='json',
        ).data['id']
        self.client.post(f'/api/wage-monthly-closings/{closing_id}/generate/')
        resp = self.client.post(f'/api/wage-monthly-closings/{closing_id}/confirm/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['status'], 'confirmed')
