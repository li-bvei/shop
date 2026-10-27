from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.utils import timezone

from paymentmethods.models import PaymentMethodDef
from common.test_utils import ApiTestCase

from .models import CashRegisterDefaults, DailyReport, DailyReportHistory
from .report_lock import issue_unlock_token


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

    def test_amount_under_a_deleted_payment_method_survives_resave(self):
        """Deleting a payment method through the API (PaymentMethodDefViewSet
        soft-deletes it — see paymentmethods/views.py) must not make a
        report re-save silently drop whatever money was already recorded
        under its id; before the soft-delete fix, save() couldn't find the
        (hard-deleted) method and dropped the key on every subsequent save."""
        method = PaymentMethodDef.objects.create(branch=self.branch_a, code='temp-method', custom_name='临时方式')
        report = DailyReport.objects.create(
            branch=self.branch_a, date='2026-02-05', total_revenue=5000,
            payment_amounts={str(method.id): 2000},
        )
        self.login_as(self.branch_a_user)
        resp = self.client.delete(f'/api/payment-methods/{method.id}/')
        self.assertEqual(resp.status_code, 204)

        report.total_revenue = 6000
        report.save()
        report.refresh_from_db()
        self.assertEqual(report.payment_amounts.get(str(method.id)), 2000)

    def test_person_in_charge_must_belong_to_report_branch(self):
        from staff.models import StaffMember
        other = StaffMember.objects.create(name='other', branch=self.branch_b)
        self.login_as(self.branch_a_user)
        response = self.client.post('/api/daily-reports/', {
            'date': '2026-02-01', 'total_revenue': 183430, 'person_in_charge': other.id,
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(DailyReport.objects.filter(date='2026-02-01').exists())

    def test_non_cash_total_may_exceed_revenue_and_cash_goes_negative(self):
        credit = PaymentMethodDef.objects.get(branch=self.branch_a, code='creditCard')
        cash = PaymentMethodDef.objects.get(branch=self.branch_a, protected=True)
        self.login_as(self.branch_a_user)
        response = self.client.post('/api/daily-reports/', {
            'branch': self.branch_a.id, 'date': '2026-02-03', 'total_revenue': 100,
            'payment_amounts': {str(credit.id): 101},
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        report = DailyReport.objects.get(id=response.data['id'])
        self.assertEqual(report.payment_amounts[str(cash.id)], -1)

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


class CashRegisterFloatTests(ApiTestCase):
    """The float is owned by each report: replenishing it on one day must
    never change another day's stored value."""

    def test_float_is_stored_per_report_and_independent_of_branch_defaults(self):
        CashRegisterDefaults.objects.create(branch=self.branch_a, denomination_defaults={'500': 99})
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/daily-reports/', {
            'branch': self.branch_a.id, 'date': '2026-10-01', 'total_revenue': 1000,
            'cash_register_float': {'500': 10, '100': 20},
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['cash_register_float'], {'500': 10, '100': 20, '50': 0, '10': 0, '5': 0})
        CashRegisterDefaults.objects.filter(branch=self.branch_a).update(denomination_defaults={'500': 1})
        report = DailyReport.objects.get(id=resp.data['id'])
        self.assertEqual(report.cash_register_float['500'], 10)

    def test_patch_without_float_keeps_stored_float(self):
        self.login_as(self.branch_a_user)
        created = self.client.post('/api/daily-reports/', {
            'branch': self.branch_a.id, 'date': '2026-10-01', 'total_revenue': 1000, 'cash_register_float': {'500': 7},
        }, format='json')
        resp = self.client.patch(f"/api/daily-reports/{created.data['id']}/", {'total_revenue': 2000}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['cash_register_float']['500'], 7)

    def test_float_can_be_lowered_on_a_later_day_without_touching_earlier_day(self):
        self.login_as(self.branch_a_user)
        day1 = self.client.post('/api/daily-reports/', {
            'branch': self.branch_a.id, 'date': '2026-10-01', 'total_revenue': 1000, 'cash_register_float': {'500': 10},
        }, format='json')
        self.client.post('/api/daily-reports/', {
            'branch': self.branch_a.id, 'date': '2026-10-02', 'total_revenue': 1000, 'cash_register_float': {'500': 4},
        }, format='json')
        self.assertEqual(DailyReport.objects.get(id=day1.data['id']).cash_register_float['500'], 10)

    def test_float_rejects_unknown_negative_and_fractional(self):
        self.login_as(self.branch_a_user)
        for i, bad in enumerate(({'10000': 1}, {'500': -1}, {'500': 1.5}, {'500': 'x'})):
            resp = self.client.post('/api/daily-reports/', {
                'branch': self.branch_a.id, 'date': f'2026-10-{i + 10:02d}', 'total_revenue': 1000, 'cash_register_float': bad,
            }, format='json')
            self.assertEqual(resp.status_code, 400, bad)

    def test_previous_returns_latest_earlier_report_only(self):
        DailyReport.objects.create(branch=self.branch_a, date='2026-10-01', cash_register_float={'500': 1})
        DailyReport.objects.create(branch=self.branch_a, date='2026-10-03', cash_register_float={'500': 3})
        DailyReport.objects.create(branch=self.branch_a, date='2026-10-05', cash_register_float={'500': 5})
        DailyReport.objects.create(branch=self.branch_b, date='2026-10-04', cash_register_float={'500': 44})
        self.login_as(self.branch_a_user)
        resp = self.client.get('/api/daily-reports/previous/?date=2026-10-04')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([r['date'] for r in resp.data], ['2026-10-03'])
        self.assertEqual(self.client.get('/api/daily-reports/previous/?date=2026-10-01').data, [])
        self.assertEqual(self.client.get('/api/daily-reports/previous/').status_code, 400)

    def test_admin_previous_is_scoped_by_branch_param(self):
        DailyReport.objects.create(branch=self.branch_a, date='2026-10-03', cash_register_float={'500': 3})
        DailyReport.objects.create(branch=self.branch_b, date='2026-10-02', cash_register_float={'500': 2})
        self.login_as(self.admin)
        resp = self.client.get(f'/api/daily-reports/previous/?date=2026-10-04&branch={self.branch_b.id}')
        self.assertEqual([r['date'] for r in resp.data], ['2026-10-02'])


class CashRegisterFloatBackfillTests(ApiTestCase):
    def test_backfill_freezes_current_default_into_reports_on_or_after_cutoff_only(self):
        import importlib
        from django.apps import apps
        migration = importlib.import_module('dailyreports.migrations.0004_dailyreport_cash_register_float')
        CashRegisterDefaults.objects.create(branch=self.branch_a, denomination_defaults={'500': 12, '100': 3})
        old = DailyReport.objects.create(branch=self.branch_a, date='2026-09-14')
        new = DailyReport.objects.create(branch=self.branch_a, date='2026-09-15')
        no_defaults = DailyReport.objects.create(branch=self.branch_b, date='2026-09-20')
        before = DailyReport.objects.get(id=new.id).updated_at
        migration.backfill_float(apps, None)
        for r in (old, new, no_defaults):
            r.refresh_from_db()
        self.assertEqual(old.cash_register_float, {})
        self.assertEqual(new.cash_register_float, {'500': 12, '100': 3})
        self.assertEqual(no_defaults.cash_register_float, {})
        self.assertEqual(new.updated_at, before)


class CashRegisterDefaultsTests(ApiTestCase):
    def test_lazily_created_with_documented_defaults(self):
        self.login_as(self.branch_a_user)
        resp = self.client.get('/api/cash-register-defaults/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['denomination_defaults'], {})
        self.assertEqual(resp.data['expected_total'], 130000)
        self.assertEqual(CashRegisterDefaults.objects.filter(branch=self.branch_a).count(), 1)

    def test_branch_account_can_update_own_defaults(self):
        self.login_as(self.branch_a_user)
        resp = self.client.patch('/api/cash-register-defaults/', {
            'denomination_defaults': {'500': 10, '100': 20, '50': 5, '10': 10, '5': 4},
            'expected_total': 150000,
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['denomination_defaults']['100'], 20)
        self.assertEqual(resp.data['expected_total'], 150000)

    def test_unknown_denomination_rejected(self):
        self.login_as(self.branch_a_user)
        resp = self.client.patch('/api/cash-register-defaults/', {
            'denomination_defaults': {'10000': 1},
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_negative_count_rejected(self):
        self.login_as(self.branch_a_user)
        resp = self.client.patch('/api/cash-register-defaults/', {
            'denomination_defaults': {'500': -1},
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_branch_accounts_are_isolated(self):
        self.login_as(self.branch_a_user)
        self.client.patch('/api/cash-register-defaults/', {
            'denomination_defaults': {'500': 10},
        }, format='json')
        self.login_as(self.branch_b_user)
        resp = self.client.get('/api/cash-register-defaults/')
        self.assertEqual(resp.data['denomination_defaults'], {})

    def test_admin_requires_branch_param(self):
        self.login_as(self.admin)
        resp = self.client.get('/api/cash-register-defaults/')
        self.assertEqual(resp.status_code, 400)

    def test_admin_can_read_specific_branch(self):
        CashRegisterDefaults.objects.create(branch=self.branch_a, expected_total=99999)
        self.login_as(self.admin)
        resp = self.client.get(f'/api/cash-register-defaults/?branch={self.branch_a.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['expected_total'], 99999)

    def test_editing_defaults_never_touches_saved_reports(self):
        report = DailyReport.objects.create(
            branch=self.branch_a, date='2026-01-01', total_revenue=1000,
            cash_register_counts={'500': 3},
        )
        self.login_as(self.branch_a_user)
        self.client.patch('/api/cash-register-defaults/', {
            'denomination_defaults': {'500': 99},
        }, format='json')
        report.refresh_from_db()
        self.assertEqual(report.cash_register_counts, {'500': 3})


class ReportLockTests(ApiTestCase):
    """A report dated before today is locked once the org has opted in by
    setting a report_unlock_password_hash — writes need a valid unlock
    token (see report_lock.py), obtained via /api/daily-reports-unlock/."""

    def setUp(self):
        super().setUp()
        self.yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
        self.today = timezone.localdate().isoformat()

    def test_org_without_unlock_password_is_never_locked(self):
        report = DailyReport.objects.create(branch=self.branch_a, date=self.yesterday, total_revenue=1000)
        self.login_as(self.branch_a_user)
        resp = self.client.patch(f'/api/daily-reports/{report.id}/', {'total_revenue': 2000}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_past_date_write_is_rejected_without_unlock_token(self):
        self.org.report_unlock_password_hash = make_password('secret1')
        self.org.save(update_fields=['report_unlock_password_hash'])
        day_before = (timezone.localdate() - timedelta(days=2)).isoformat()
        report = DailyReport.objects.create(branch=self.branch_a, date=self.yesterday, total_revenue=1000)

        self.login_as(self.branch_a_user)
        create_resp = self.client.post('/api/daily-reports/', {
            'branch': self.branch_a.id, 'date': day_before, 'total_revenue': 500,
        }, format='json')
        self.assertEqual(create_resp.status_code, 403)

        update_resp = self.client.patch(f'/api/daily-reports/{report.id}/', {'total_revenue': 2000}, format='json')
        self.assertEqual(update_resp.status_code, 403)
        report.refresh_from_db()
        self.assertEqual(report.total_revenue, 1000)

    def test_todays_date_is_never_locked_even_with_password_configured(self):
        self.org.report_unlock_password_hash = make_password('secret1')
        self.org.save(update_fields=['report_unlock_password_hash'])
        report = DailyReport.objects.create(branch=self.branch_a, date=self.today, total_revenue=1000)
        self.login_as(self.branch_a_user)
        resp = self.client.patch(f'/api/daily-reports/{report.id}/', {'total_revenue': 2000}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_valid_unlock_token_allows_past_date_write(self):
        self.org.report_unlock_password_hash = make_password('secret1')
        self.org.save(update_fields=['report_unlock_password_hash'])
        report = DailyReport.objects.create(branch=self.branch_a, date=self.yesterday, total_revenue=1000)

        self.login_as(self.branch_a_user)
        token = issue_unlock_token(self.branch_a_user)
        resp = self.client.patch(
            f'/api/daily-reports/{report.id}/', {'total_revenue': 2000}, format='json',
            HTTP_X_REPORT_UNLOCK_TOKEN=token,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        report.refresh_from_db()
        self.assertEqual(report.total_revenue, 2000)

    def test_unlock_token_is_scoped_to_the_user_who_obtained_it(self):
        self.org.report_unlock_password_hash = make_password('secret1')
        self.org.save(update_fields=['report_unlock_password_hash'])
        report = DailyReport.objects.create(branch=self.branch_a, date=self.yesterday, total_revenue=1000)

        token = issue_unlock_token(self.branch_b_user)
        self.login_as(self.branch_a_user)
        resp = self.client.patch(
            f'/api/daily-reports/{report.id}/', {'total_revenue': 2000}, format='json',
            HTTP_X_REPORT_UNLOCK_TOKEN=token,
        )
        self.assertEqual(resp.status_code, 403)

    def test_unlock_endpoint_rejects_wrong_password_and_grants_token_for_right_one(self):
        self.org.report_unlock_password_hash = make_password('secret1')
        self.org.save(update_fields=['report_unlock_password_hash'])
        self.login_as(self.branch_a_user)

        wrong = self.client.post('/api/daily-reports-unlock/', {'password': 'nope'}, format='json')
        self.assertEqual(wrong.status_code, 400)

        right = self.client.post('/api/daily-reports-unlock/', {'password': 'secret1'}, format='json')
        self.assertEqual(right.status_code, 200, right.content)
        self.assertIn('token', right.data)

        report = DailyReport.objects.create(branch=self.branch_a, date=self.yesterday, total_revenue=1000)
        resp = self.client.patch(
            f'/api/daily-reports/{report.id}/', {'total_revenue': 2000}, format='json',
            HTTP_X_REPORT_UNLOCK_TOKEN=right.data['token'],
        )
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_unlock_endpoint_rate_limits_repeated_wrong_passwords(self):
        self.org.report_unlock_password_hash = make_password('secret1')
        self.org.save(update_fields=['report_unlock_password_hash'])
        self.login_as(self.branch_a_user)
        for _ in range(5):
            resp = self.client.post('/api/daily-reports-unlock/', {'password': 'nope'}, format='json')
            self.assertEqual(resp.status_code, 400)
        locked_out = self.client.post('/api/daily-reports-unlock/', {'password': 'secret1'}, format='json')
        self.assertEqual(locked_out.status_code, 403)

    def test_unlock_endpoint_404s_when_org_has_not_configured_a_password(self):
        self.login_as(self.branch_a_user)
        resp = self.client.post('/api/daily-reports-unlock/', {'password': 'anything'}, format='json')
        self.assertEqual(resp.status_code, 404)


class PreviousShortageTests(ApiTestCase):
    """昨日不足分 is an ordinary hand-editable non-cash row; the only thing that
    marks it is `auto_source`, which tells the frontend to pre-fill it from the
    previous day. The server stores whatever amount is sent."""

    def setUp(self):
        super().setUp()
        self.cash = PaymentMethodDef.objects.get(branch=self.branch_a, protected=True)
        self.auto = PaymentMethodDef.objects.get(branch=self.branch_a, code='previousShortage')
        self.login_as(self.branch_a_user)

    def test_seeded_row_is_flagged_auto(self):
        self.assertEqual(self.auto.auto_source, 'previous_shortage')

    def test_rows_named_like_the_manual_one_are_flagged_on_creation(self):
        manual = PaymentMethodDef.objects.create(branch=self.branch_a, code='custom-1', custom_name='昨日不足分')
        self.assertEqual(manual.auto_source, 'previous_shortage')
        other = PaymentMethodDef.objects.create(branch=self.branch_a, code='custom-2', custom_name='商品券')
        self.assertEqual(other.auto_source, '')

    def test_hand_entered_amount_is_saved_as_is_and_lowers_cash(self):
        resp = self.client.post('/api/daily-reports/', {
            'branch': self.branch_a.id, 'date': '2026-10-02', 'total_revenue': 10000,
            'payment_amounts': {str(self.auto.id): 27881},
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        report = DailyReport.objects.get(id=resp.data['id'])
        self.assertEqual(report.payment_amounts[str(self.auto.id)], 27881)
        self.assertEqual(report.payment_amounts[str(self.cash.id)], 10000 - 27881)

    def test_editing_a_day_never_rewrites_another_days_amount(self):
        day1 = self.client.post('/api/daily-reports/', {
            'branch': self.branch_a.id, 'date': '2026-10-01', 'total_revenue': 5000,
        }, format='json')
        day2 = self.client.post('/api/daily-reports/', {
            'branch': self.branch_a.id, 'date': '2026-10-02', 'total_revenue': 10000,
            'payment_amounts': {str(self.auto.id): 1234},
        }, format='json')
        self.client.patch(f"/api/daily-reports/{day1.data['id']}/", {
            'expenses': [{'itemName': 'x', 'amount': 9000, 'purpose': ''}],
        }, format='json')
        self.assertEqual(DailyReport.objects.get(id=day2.data['id']).payment_amounts[str(self.auto.id)], 1234)
