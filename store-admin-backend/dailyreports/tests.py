from paymentmethods.models import PaymentMethodDef
from common.test_utils import ApiTestCase

from .models import DailyReport, DailyReportHistory


class CashCalculationTests(ApiTestCase):
    """Regression coverage for the historical bug where cash was computed
    against a hardcoded literal 'cash' key that stopped matching anything
    once payment methods became per-branch with real numeric ids."""

    def test_cash_equals_revenue_minus_non_cash(self):
        credit_card = PaymentMethodDef.objects.get(branch=self.branch_a, code='creditCard')
        paypay = PaymentMethodDef.objects.get(branch=self.branch_a, code='paypay')
        cash_method = PaymentMethodDef.objects.get(branch=self.branch_a, protected=True)

        report = DailyReport.objects.create(
            branch=self.branch_a, date='2026-01-01', total_revenue=183430,
            payment_amounts={
                str(credit_card.id): 66130,
                str(paypay.id): 19080,
                str(cash_method.id): 0,  # deliberately wrong client value, must be overwritten
            },
        )
        report.refresh_from_db()
        self.assertEqual(report.payment_amounts[str(cash_method.id)], 183430 - 66130 - 19080)

    def test_unknown_non_cash_key_is_cleaned_and_never_reduces_cash(self):
        cash_method = PaymentMethodDef.objects.get(branch=self.branch_a, protected=True)
        report = DailyReport.objects.create(
            branch=self.branch_a, date='2026-01-02', total_revenue=1000,
            payment_amounts={'999999': 500},
        )
        report.refresh_from_db()
        self.assertEqual(report.payment_amounts, {str(cash_method.id): 1000})

    def test_api_rejects_unknown_other_branch_and_deleted_payment_ids(self):
        other = PaymentMethodDef.objects.get(branch=self.branch_b, code='paypay')
        deleted = PaymentMethodDef.objects.create(branch=self.branch_a, code='temporary', custom_name='tmp')
        deleted_id = deleted.id
        deleted.delete()
        self.login_as(self.branch_a_user)
        for malicious_id in ('999999', str(other.id), str(deleted_id)):
            response = self.client.post('/api/daily-reports/', {
                'date': f'2026-02-{int(malicious_id[-1]) + 10:02d}',
                'total_revenue': 183430, 'payment_amounts': {malicious_id: 100},
            }, format='json')
            self.assertEqual(response.status_code, 400)

    def test_person_in_charge_must_belong_to_report_branch(self):
        from staff.models import StaffMember
        other = StaffMember.objects.create(name='other', branch=self.branch_b)
        self.login_as(self.branch_a_user)
        response = self.client.post('/api/daily-reports/', {
            'date': '2026-02-01', 'total_revenue': 183430, 'person_in_charge': other.id,
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(DailyReport.objects.filter(date='2026-02-01').exists())

    def test_non_cash_total_cannot_make_computed_cash_negative(self):
        credit = PaymentMethodDef.objects.get(branch=self.branch_a, code='creditCard')
        self.login_as(self.branch_a_user)
        response = self.client.post('/api/daily-reports/', {
            'date': '2026-02-03', 'total_revenue': 100,
            'payment_amounts': {str(credit.id): 101},
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_cash_register_counts_are_saved_and_normalized(self):
        self.login_as(self.branch_a_user)
        response = self.client.post('/api/daily-reports/', {
            'branch': self.branch_a.id,
            'date': '2026-02-04',
            'total_revenue': 1000,
            'cash_register_counts': {'10000': 2, '1000': 3},
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['cash_register_counts']['10000'], 2)
        self.assertEqual(response.data['cash_register_counts']['1000'], 3)
        self.assertEqual(response.data['cash_register_counts']['1'], 0)

    def test_cash_register_counts_reject_negative_or_unknown_values(self):
        self.login_as(self.branch_a_user)
        for counts in ({'500': -1}, {'2000': 1}, {'100': 1.5}):
            response = self.client.post('/api/daily-reports/', {
                'date': f'2026-02-{10 + len(counts):02d}',
                'total_revenue': 1000,
                'cash_register_counts': counts,
            }, format='json')
            self.assertEqual(response.status_code, 400)


class HistoryAppendOnlyTests(ApiTestCase):
    def test_history_patch_not_allowed(self):
        self.login_as(self.branch_a_user)
        create_resp = self.client.post('/api/daily-report-history/', {
            'date': '2026-01-01', 'total_revenue': 1000, 'cash_remaining': 800, 'data': {},
        }, format='json')
        self.assertEqual(create_resp.status_code, 201)
        patch_resp = self.client.patch(f'/api/daily-report-history/{create_resp.data["id"]}/', {
            'total_revenue': 2000,
        }, format='json')
        self.assertEqual(patch_resp.status_code, 405)

    def test_history_delete_not_allowed(self):
        self.login_as(self.branch_a_user)
        create_resp = self.client.post('/api/daily-report-history/', {
            'date': '2026-01-01', 'total_revenue': 1000, 'cash_remaining': 800, 'data': {},
        }, format='json')
        delete_resp = self.client.delete(f'/api/daily-report-history/{create_resp.data["id"]}/')
        self.assertEqual(delete_resp.status_code, 405)

    def test_edited_by_is_server_set_not_client_supplied(self):
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/daily-report-history/', {
            'date': '2026-01-01', 'total_revenue': 1000, 'cash_remaining': 800, 'data': {},
            'edited_by_name': 'someone-else',
        }, format='json')
        entry = DailyReportHistory.objects.get(id=resp.data['id'])
        self.assertEqual(entry.edited_by_id, self.branch_a_user.id)
        self.assertNotEqual(entry.edited_by_name, 'someone-else')


class BranchScopingTests(ApiTestCase):
    def test_branch_account_cannot_see_other_branch_reports(self):
        DailyReport.objects.create(branch=self.branch_b, date='2026-01-01', total_revenue=5000)
        self.login_as(self.branch_a_user)
        resp = self.client.get('/api/daily-reports/')
        self.assertEqual(resp.data, [])

    def test_branch_account_create_forces_own_branch(self):
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/daily-reports/', {
            'branch': self.branch_b.id, 'date': '2026-01-01', 'total_revenue': 1000,
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['branch'], self.branch_a.id)
