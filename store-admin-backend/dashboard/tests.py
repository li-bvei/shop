from datetime import date
from decimal import Decimal

from common.test_utils import ApiTestCase

from dailyreports.models import DailyReport, DailyReportHistory
from purchasing.models import PurchaseRecord, Supplier

from .analysis import month_bounds, previous_month


class MonthBoundsTests(ApiTestCase):
    def test_previous_month_of_january_is_december_last_year(self):
        self.assertEqual(previous_month(2026, 1), (2025, 12))

    def test_previous_month_within_same_year(self):
        self.assertEqual(previous_month(2026, 8), (2026, 7))

    def test_month_bounds_handles_28_29_30_31_day_months(self):
        self.assertEqual(month_bounds(2026, 2), (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(month_bounds(2024, 2), (date(2024, 2, 1), date(2024, 2, 29)))  # leap year
        self.assertEqual(month_bounds(2026, 4), (date(2026, 4, 1), date(2026, 4, 30)))
        self.assertEqual(month_bounds(2026, 1), (date(2026, 1, 1), date(2026, 1, 31)))


class MonthlyAnalysisPermissionTests(ApiTestCase):
    def test_staff_gets_403(self):
        self.login_as(self.staff_user)
        resp = self.client.get('/api/dashboard/monthly-analysis/?month=2026-01')
        self.assertEqual(resp.status_code, 403)

    def test_missing_month_param_is_400_not_500(self):
        self.login_as(self.admin)
        resp = self.client.get('/api/dashboard/monthly-analysis/')
        self.assertEqual(resp.status_code, 400)

    def test_malformed_month_param_is_400_not_500(self):
        self.login_as(self.admin)
        resp = self.client.get('/api/dashboard/monthly-analysis/?month=not-a-month')
        self.assertEqual(resp.status_code, 400)

    def test_branch_account_cannot_escalate_via_branch_param(self):
        DailyReport.objects.create(branch=self.branch_b, date=date(2026, 1, 5), total_revenue=99999, total_customers=10)
        self.login_as(self.branch_a_user)
        resp = self.client.get(f'/api/dashboard/monthly-analysis/?month=2026-01&branch={self.branch_b.id}')
        self.assertEqual(resp.status_code, 200)
        # Silently corrected to their own branch — branch_b's revenue must not leak in.
        self.assertEqual(resp.data['revenue'], '0')

    def test_admin_with_no_branch_param_sees_all_branches_combined(self):
        DailyReport.objects.create(branch=self.branch_a, date=date(2026, 1, 5), total_revenue=1000, total_customers=10)
        DailyReport.objects.create(branch=self.branch_b, date=date(2026, 1, 6), total_revenue=2000, total_customers=20)
        self.login_as(self.admin)
        resp = self.client.get('/api/dashboard/monthly-analysis/?month=2026-01')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['revenue'], '3000')
        self.assertIsNotNone(resp.data['branchComparison'])

    def test_admin_with_branch_param_sees_single_branch(self):
        DailyReport.objects.create(branch=self.branch_a, date=date(2026, 1, 5), total_revenue=1000, total_customers=10)
        DailyReport.objects.create(branch=self.branch_b, date=date(2026, 1, 6), total_revenue=2000, total_customers=20)
        self.login_as(self.admin)
        resp = self.client.get(f'/api/dashboard/monthly-analysis/?month=2026-01&branch={self.branch_a.id}')
        self.assertEqual(resp.data['revenue'], '1000')
        self.assertIsNone(resp.data['branchComparison'])

    def test_unknown_branch_param_is_400(self):
        self.login_as(self.admin)
        resp = self.client.get('/api/dashboard/monthly-analysis/?month=2026-01&branch=does-not-exist')
        self.assertEqual(resp.status_code, 400)


class MonthlyAnalysisEmptyDataTests(ApiTestCase):
    def test_empty_month_returns_safe_zero_values_not_500(self):
        self.login_as(self.admin)
        resp = self.client.get(f'/api/dashboard/monthly-analysis/?month=2026-01&branch={self.branch_a.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['revenue'], '0')
        self.assertEqual(resp.data['avgSpend'], '0')
        self.assertIsNone(resp.data['revenueDeltaPct'])
        self.assertIsNone(resp.data['highestRevenueDay'])
        self.assertEqual(resp.data['daysWithReports'], 0)


class MonthlyAnalysisCalculationTests(ApiTestCase):
    def test_revenue_expenses_purchasing_and_tentative_gap(self):
        DailyReport.objects.create(
            branch=self.branch_a, date=date(2026, 1, 5), total_revenue=100000, total_customers=50,
            expenses=[{'itemName': '野菜', 'amount': 3000, 'purpose': 'x'}],
        )
        supplier = Supplier.objects.create(organization=self.org, name='测试供应商')
        PurchaseRecord.objects.create(
            branch=self.branch_a, date=date(2026, 1, 5), supplier=supplier, item_name='x',
            quantity=1, unit_price=20000,
        )
        self.login_as(self.admin)
        resp = self.client.get(f'/api/dashboard/monthly-analysis/?month=2026-01&branch={self.branch_a.id}')
        self.assertEqual(resp.data['revenue'], '100000')
        self.assertEqual(resp.data['purchasing'], '20000')
        self.assertEqual(resp.data['expenses'], '3000')
        # gap = 100000 - 20000 - 3000 - 0(no wages) = 77000
        self.assertEqual(resp.data['tentativeOperatingGap'], '77000')
        self.assertEqual(resp.data['avgSpend'], '2000')  # 100000/50

    def test_history_edit_count_does_not_affect_revenue(self):
        report = DailyReport.objects.create(
            branch=self.branch_a, date=date(2026, 1, 5), total_revenue=1000, total_customers=10,
        )
        for _ in range(4):
            DailyReportHistory.objects.create(
                branch=self.branch_a, date=date(2026, 1, 5), edited_by=self.branch_a_user,
                edited_by_name='x', total_revenue=1000, cash_remaining=1000, data={},
            )
        self.login_as(self.admin)
        resp = self.client.get(f'/api/dashboard/monthly-analysis/?month=2026-01&branch={self.branch_a.id}')
        # Revenue must come from the live DailyReport only, once — never
        # multiplied by however many history snapshots exist for that date.
        self.assertEqual(resp.data['revenue'], '1000')
        detail_row = next(r for r in resp.data['dailyDetail'] if r['date'] == '2026-01-05')
        self.assertEqual(detail_row['editCount'], 4)
        heavy_edit_insights = [i for i in resp.data['insights'] if i['rule'] == 'daily_report_heavily_edited']
        self.assertEqual(len(heavy_edit_insights), 1)


class MonthlyAnalysisTerminologyTests(ApiTestCase):
    """Guards against regressions in the required neutral/careful wording."""

    def test_no_forbidden_words_anywhere_in_the_response(self):
        DailyReport.objects.create(branch=self.branch_a, date=date(2026, 1, 5), total_revenue=1000, total_customers=10)
        self.login_as(self.admin)
        resp = self.client.get(f'/api/dashboard/monthly-analysis/?month=2026-01&branch={self.branch_a.id}')
        blob = str(resp.data)
        for forbidden in ['利润', '舞弊', '经营异常', '毛利率', '人工成本率']:
            self.assertNotIn(forbidden, blob, f'forbidden term "{forbidden}" leaked into the response')


class MonthlyAnalysisExcludesPayrollTests(ApiTestCase):
    """暂定经营差额 = revenue − purchasing − expenses, with NO payroll term
    (removed at the user's request — wages live only in the 工资 feature)."""

    def test_response_has_no_wage_fields_and_gap_ignores_payroll(self):
        from scheduling.models import ActualWorkRecord
        from wages.models import WageRule

        DailyReport.objects.create(
            branch=self.branch_a, date=date(2026, 1, 5), total_revenue=100000, total_customers=100,
        )
        WageRule.objects.create(
            employee=self.staff_employee, effective_from=date(2026, 1, 1), hourly_rate=1000,
            transportation_type='monthly', transportation_amount=500,
        )
        ActualWorkRecord.objects.create(
            branch=self.branch_a, employee=self.staff_employee, work_date=date(2026, 1, 5),
            actual_start='09:00', actual_end='17:00', actual_break_minutes=60,
            status=ActualWorkRecord.Status.MANAGER_CONFIRMED,
        )
        self.login_as(self.admin)
        closing_resp = self.client.post(
            '/api/wage-monthly-closings/', {'branch': self.branch_a.id, 'month': '2026-01-01'}, format='json',
        )
        self.client.post(f'/api/wage-monthly-closings/{closing_resp.data["id"]}/generate/')

        resp = self.client.get(f'/api/dashboard/monthly-analysis/?month=2026-01&branch={self.branch_a.id}')
        self.assertNotIn('wageTotal', resp.data)
        self.assertNotIn('wageStatus', resp.data)
        # gap = 100000 revenue − 0 purchasing − 0 expenses, payroll untouched
        self.assertEqual(resp.data['tentativeOperatingGap'], '100000')
        self.assertFalse(any(i['rule'] == 'hourly_wage_to_revenue_ratio' for i in resp.data['insights']))
