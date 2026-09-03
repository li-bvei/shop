from datetime import time, timedelta

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from common.test_utils import ApiTestCase, TwoOrganizationApiTestCase

from .models import (
    Campaign, CheckInRecord, Customer, LotteryDraw, Milestone, MilestoneClaim, PointsLedger, Prize,
    RewardType, RiskEvent, SpendVerification, StaffPermission, Voucher,
)
from .retention import purge_stale_customers
from .services import (
    adjust_points, delete_customer_by_phone, draw_lottery, expire_stale_points, make_store_token,
    redeem_points, redeem_voucher, register_customer, verify_spend, void_spend_verification,
)
from .utils import business_local_date, client_ip, normalize_birthday_md, normalize_phone


def make_campaign(branch, **kwargs):
    defaults = dict(name='DEMO/TEST 積分卡', status=Campaign.Status.ACTIVE, points_per_1000yen=10, stamp_target=5)
    defaults.update(kwargs)
    return Campaign.objects.create(branch=branch, **defaults)


def make_prize(campaign, weight, reward_type=RewardType.DRINK, config=None, **kwargs):
    defaults = dict(
        name=f'{reward_type} w{weight}', weight=weight, reward_type=reward_type,
        reward_config=config or {'label': 'test prize'},
    )
    defaults.update(kwargs)
    return Prize.objects.create(campaign=campaign, **defaults)


def only_prize(campaign, **kwargs):
    """Create a prize that is the *only* drawable one for the campaign, so
    a draw's outcome is deterministic."""
    Prize.objects.filter(campaign=campaign).update(active=False)
    return make_prize(campaign, kwargs.pop('weight', 1), **kwargs)


# ---------------------------------------------------------------------------
# utils
# ---------------------------------------------------------------------------

class NormalizePhoneTests(ApiTestCase):
    def test_variants_collapse_to_one_local_form(self):
        for raw in ['09012345678', '090-1234-5678', '090 1234 5678', '(090)1234-5678',
                    '+81 90-1234-5678', '+819012345678', '0081-90-1234-5678', '０９０１２３４５６７８']:
            self.assertEqual(normalize_phone(raw), '09012345678', raw)

    def test_landline_ten_digits(self):
        self.assertEqual(normalize_phone('06-1234-5678'), '0612345678')

    def test_rejects_garbage(self):
        for raw in ['', '123', 'abcdef', '0901234']:
            with self.assertRaises(ValidationError):
                normalize_phone(raw)

    def test_birthday_md_normalization(self):
        self.assertEqual(normalize_birthday_md('3/7'), '03-07')
        self.assertEqual(normalize_birthday_md('12-25'), '12-25')
        self.assertEqual(normalize_birthday_md('2月29日'), '02-29')  # no year -> Feb 29 ok
        self.assertEqual(normalize_birthday_md(''), '')
        for bad in ['13-01', '00-10', '01-32', 'abc', '5',
                    '02-30', '02-31', '04-31', '06-31', '09-31', '11-31']:
            with self.assertRaises(ValidationError):
                normalize_birthday_md(bad)

    def test_business_local_date_rolls_over_at_cutover(self):
        cutover = time(5, 0)
        late_night = timezone.make_aware(timezone.datetime(2026, 8, 31, 2, 30))
        morning = timezone.make_aware(timezone.datetime(2026, 8, 31, 9, 0))
        self.assertEqual(business_local_date(late_night, cutover).isoformat(), '2026-08-30')
        self.assertEqual(business_local_date(morning, cutover).isoformat(), '2026-08-31')


class ClientIpTests(ApiTestCase):
    """client_ip must not trust the caller-supplied part of
    X-Forwarded-For — that would let a guest mint a fresh throttle bucket
    per request and dodge the device-based risk rules."""

    class _Req:
        def __init__(self, xff=None, remote='203.0.113.9'):
            self.META = {'REMOTE_ADDR': remote}
            if xff is not None:
                self.META['HTTP_X_FORWARDED_FOR'] = xff

    def test_takes_the_proxy_appended_hop_not_the_spoofable_first_one(self):
        # nginx (1 proxy) appends the real peer; the client faked the rest.
        req = self._Req(xff='1.1.1.1, 2.2.2.2, 198.51.100.7')
        self.assertEqual(client_ip(req), '198.51.100.7')

    def test_falls_back_to_remote_addr_without_a_header(self):
        self.assertEqual(client_ip(self._Req(xff=None)), '203.0.113.9')

    def test_proxy_count_zero_ignores_the_header_entirely(self):
        with self.settings(PROMOTIONS_TRUSTED_PROXY_COUNT=0):
            self.assertEqual(client_ip(self._Req(xff='9.9.9.9')), '203.0.113.9')


# ---------------------------------------------------------------------------
# verify_spend service
# ---------------------------------------------------------------------------

class VerifySpendServiceTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.campaign = make_campaign(self.branch_a)
        self.customer = register_customer(organization=self.org, phone='09011112222', name='田中')

    def test_points_are_amount_floor_divided_by_1000_times_rate(self):
        v = verify_spend(
            campaign=self.campaign, branch=self.branch_a, customer=self.customer,
            amount_yen=3400, verified_by=self.staff_user,
        )
        self.assertEqual(v.points_granted, 30)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.points_balance, 30)
        self.assertEqual(self.customer.stamp_count, 1)
        ledger = PointsLedger.objects.get(customer=self.customer)
        self.assertEqual(ledger.delta, 30)
        self.assertEqual(ledger.balance_after, 30)
        self.assertEqual(ledger.reason, PointsLedger.Reason.SPEND)

    def test_second_spend_same_business_day_reuses_checkin_but_still_grants(self):
        verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                     amount_yen=2000, verified_by=self.staff_user)
        verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                     amount_yen=1000, verified_by=self.staff_user)
        self.assertEqual(CheckInRecord.objects.filter(customer=self.customer).count(), 1)
        self.assertEqual(SpendVerification.objects.filter(customer=self.customer).count(), 2)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.points_balance, 30)
        # Ledger sum always equals the cached balance.
        self.assertEqual(
            sum(PointsLedger.objects.filter(customer=self.customer).values_list('delta', flat=True)),
            self.customer.points_balance,
        )

    def test_amount_below_1000_records_visit_without_points_or_ledger_row(self):
        v = verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                         amount_yen=800, verified_by=self.staff_user)
        self.assertEqual(v.points_granted, 0)
        self.assertEqual(PointsLedger.objects.filter(customer=self.customer).count(), 0)
        self.assertEqual(CheckInRecord.objects.filter(customer=self.customer).count(), 1)

    def test_future_consumed_at_is_rejected_and_nothing_is_written(self):
        with self.assertRaises(ValidationError):
            verify_spend(
                campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                amount_yen=2000, consumed_at=timezone.now() + timedelta(hours=2),
                verified_by=self.staff_user,
            )
        self.assertEqual(SpendVerification.objects.count(), 0)
        self.assertEqual(CheckInRecord.objects.count(), 0)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.points_balance, 0)

    def test_negative_amount_rejected(self):
        with self.assertRaises(ValidationError):
            verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                         amount_yen=-100, verified_by=self.staff_user)

    def test_absurdly_large_amount_rejected(self):
        # A fat-fingered extra zero would otherwise grant a wild points total.
        with self.assertRaises(ValidationError):
            verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                         amount_yen=50_000_000, verified_by=self.staff_user)
        self.assertEqual(SpendVerification.objects.count(), 0)

    def test_verify_spend_is_idempotent_on_request_id(self):
        v1 = verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                          amount_yen=3000, verified_by=self.staff_user, request_id='sv-1')
        v2 = verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                          amount_yen=3000, verified_by=self.staff_user, request_id='sv-1')
        self.assertEqual(v1.id, v2.id)
        self.assertEqual(SpendVerification.objects.count(), 1)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.points_balance, 30)  # granted once
        # a genuinely new spend (new id) still earns
        verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                     amount_yen=3000, verified_by=self.staff_user, request_id='sv-2')
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.points_balance, 60)

    def test_campaign_time_window_gates_spend(self):
        future = make_campaign(self.branch_a, starts_at=timezone.now() + timedelta(days=1))
        with self.assertRaises(ValidationError):
            verify_spend(campaign=future, branch=self.branch_a, customer=self.customer,
                         amount_yen=2000, verified_by=self.staff_user)
        ended = make_campaign(self.branch_a, ends_at=timezone.now() - timedelta(minutes=1))
        with self.assertRaises(ValidationError):
            verify_spend(campaign=ended, branch=self.branch_a, customer=self.customer,
                         amount_yen=2000, verified_by=self.staff_user)

    def test_max_draws_per_verification_controls_granted_chances(self):
        self.campaign.direct_draw_threshold_yen = 3000
        self.campaign.max_draws_per_verification = 3
        self.campaign.save(update_fields=['direct_draw_threshold_yen', 'max_draws_per_verification'])
        verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                     amount_yen=3500, verified_by=self.staff_user)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.draw_chances, 3)

    def test_recent_backdate_ok_but_stale_backdate_rejected(self):
        # A sale earlier in the same shift, confirmed a bit later: fine.
        v = verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                         amount_yen=2000, consumed_at=timezone.now() - timedelta(hours=3),
                         verified_by=self.staff_user)
        self.assertEqual(v.points_granted, 20)
        # A confirmation dated days ago is refused.
        with self.assertRaises(ValidationError):
            verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                         amount_yen=2000, consumed_at=timezone.now() - timedelta(days=3),
                         verified_by=self.staff_user)

    def test_paused_campaign_rejected(self):
        self.campaign.status = Campaign.Status.PAUSED
        self.campaign.save(update_fields=['status'])
        with self.assertRaises(ValidationError):
            verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                         amount_yen=2000, verified_by=self.staff_user)

    def test_campaign_branch_mismatch_rejected(self):
        with self.assertRaises(ValidationError):
            verify_spend(campaign=self.campaign, branch=self.branch_b, customer=self.customer,
                         amount_yen=2000, verified_by=self.staff_user)

    def test_stamp_count_not_incremented_when_stamps_disabled(self):
        self.campaign.stamp_target = None
        self.campaign.save(update_fields=['stamp_target'])
        verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                     amount_yen=2000, verified_by=self.staff_user)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.stamp_count, 0)


class AdjustPointsAndVoidTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.campaign = make_campaign(self.branch_a)
        self.customer = register_customer(organization=self.org, phone='09011112222')

    def test_adjust_points_writes_ledger_and_requires_note(self):
        entry = adjust_points(customer=self.customer, delta=50, note='goodwill', operator=self.admin)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.points_balance, 50)
        self.assertEqual(entry.reason, PointsLedger.Reason.ADJUST)
        with self.assertRaises(ValidationError):
            adjust_points(customer=self.customer, delta=10, note='', operator=self.admin)
        with self.assertRaises(ValidationError):
            adjust_points(customer=self.customer, delta=-1000, note='x', operator=self.admin)

    def test_void_reverses_points_and_balance(self):
        v = verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                         amount_yen=5000, verified_by=self.staff_user)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.points_balance, 50)

        void_spend_verification(verification=v, operator=self.admin, reason='wrong customer')
        v.refresh_from_db()
        self.customer.refresh_from_db()
        self.assertEqual(v.status, SpendVerification.Status.VOIDED)
        self.assertEqual(self.customer.points_balance, 0)
        self.assertEqual(
            sum(PointsLedger.objects.filter(customer=self.customer).values_list('delta', flat=True)), 0,
        )
        with self.assertRaises(ValidationError):
            void_spend_verification(verification=v, operator=self.admin, reason='again')

    def test_void_requires_reason(self):
        v = verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                         amount_yen=2000, verified_by=self.staff_user)
        with self.assertRaises(ValidationError):
            void_spend_verification(verification=v, operator=self.admin, reason='   ')


class DeleteCustomerTests(ApiTestCase):
    def test_erasure_detaches_records_and_removes_customer(self):
        campaign = make_campaign(self.branch_a)
        customer = register_customer(organization=self.org, phone='09011112222', name='田中')
        verify_spend(campaign=campaign, branch=self.branch_a, customer=customer,
                     amount_yen=3000, verified_by=self.staff_user)

        result = delete_customer_by_phone(organization=self.org, phone='090-1111-2222', operator=self.admin)
        self.assertEqual(result['verifications_detached'], 1)
        self.assertFalse(Customer.objects.filter(phone='09011112222').exists())

        v = SpendVerification.objects.get()
        self.assertIsNone(v.customer_id)
        self.assertTrue(v.customer_deleted)
        ci = CheckInRecord.objects.get()
        self.assertIsNone(ci.customer_id)
        self.assertTrue(ci.customer_deleted)
        self.assertTrue(PointsLedger.objects.filter(customer__isnull=True).exists())


# ---------------------------------------------------------------------------
# Guest API
# ---------------------------------------------------------------------------

class GuestApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.campaign = make_campaign(self.branch_a)
        self.store_token = make_store_token(self.campaign)

    def test_register_creates_customer_and_sets_cookie(self):
        resp = self.client.post('/api/guest/register/', {
            'store_token': self.store_token, 'phone': '090-1234-5678', 'name': '山田',
            'birthday_md': '3/7', 'consent': True,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertIn('card_token', resp.data)
        self.assertIn('pc_guest', resp.cookies)
        customer = Customer.objects.get(phone='09012345678')
        self.assertEqual(customer.name, '山田')
        self.assertEqual(customer.birthday_md, '03-07')
        self.assertEqual(customer.organization_id, self.org.id)
        self.assertIsNotNone(customer.privacy_consented_at)
        self.assertEqual(customer.registered_campaign_id, self.campaign.id)

    def test_register_without_consent_is_rejected(self):
        resp = self.client.post('/api/guest/register/', {
            'store_token': self.store_token, 'phone': '09012345678', 'consent': False,
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Customer.objects.exists())

    def test_register_rejects_invalid_store_token(self):
        resp = self.client.post('/api/guest/register/', {
            'store_token': 'not-a-real-token', 'phone': '09012345678',
            'birthday_md': '03-07', 'consent': True,
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('store-token-invalid', str(resp.data))

    def test_register_rejects_inactive_campaign_token(self):
        self.campaign.status = Campaign.Status.PAUSED
        self.campaign.save(update_fields=['status'])
        resp = self.client.post('/api/guest/register/', {
            'store_token': self.store_token, 'phone': '09012345678',
            'birthday_md': '03-07', 'consent': True,
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_register_requires_a_birthday(self):
        resp = self.client.post('/api/guest/register/', {
            'store_token': self.store_token, 'phone': '09012345678', 'consent': True,
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('birthday', str(resp.data))
        self.assertFalse(Customer.objects.exists())

    def test_store_context_returns_the_chain_brand(self):
        self.org.logo_url = 'https://cdn.example.com/logo.png'
        self.org.save(update_fields=['logo_url'])
        resp = self.client.get('/api/guest/store-context/', {'t': self.store_token})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['org_name_ja'], self.org.name_ja)
        self.assertEqual(resp.data['org_logo_url'], 'https://cdn.example.com/logo.png')
        # never leaks the campaign / token internals
        self.assertNotIn('card_token', resp.data)

    def test_store_context_rejects_a_bad_token(self):
        resp = self.client.get('/api/guest/store-context/', {'t': 'not-a-real-token'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('store-token-invalid', str(resp.data))

    def test_public_register_ignores_spend_fields(self):
        resp = self.client.post('/api/guest/register/', {
            'store_token': self.store_token, 'phone': '09012345678',
            'birthday_md': '03-07', 'consent': True,
            'amount_yen': 999999, 'points_granted': 5000, 'points_balance': 5000,
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        customer = Customer.objects.get()
        self.assertEqual(customer.points_balance, 0)

    def test_register_never_hands_back_an_existing_cards_credential(self):
        # A card takeover would otherwise be: register with someone's phone,
        # get their card_token, spend their points.
        alice = register_customer(organization=self.org, phone='09012345678', campaign=self.campaign)
        alice_token = alice.card_token

        resp = self.client.post('/api/guest/register/', {
            'store_token': self.store_token, 'phone': '090-1234-5678',
            'name': 'Mallory', 'birthday_md': '01-01', 'consent': True,
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data.get('existing'))
        self.assertNotIn('card_token', resp.data)
        self.assertNotIn('pc_guest', resp.cookies)

        # Alice's profile was not touched by the stranger's request.
        alice.refresh_from_db()
        self.assertEqual(alice.card_token, alice_token)
        self.assertEqual(alice.name, '')
        self.assertEqual(alice.birthday_md, '')

    def test_card_header_token_wins_over_a_stale_cookie(self):
        from rest_framework.test import APIClient

        r1 = self.client.post('/api/guest/register/', {
            'store_token': self.store_token, 'phone': '09011110000', 'birthday_md': '03-07', 'consent': True,
        }, format='json')
        good_token = r1.data['card_token']

        client = APIClient()
        client.cookies['pc_guest'] = 'a-stale-deleted-token'
        resp = client.get('/api/guest/card/', HTTP_X_GUEST_TOKEN=good_token)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['card_token'], good_token)

    def test_card_requires_matching_guest_token(self):
        from rest_framework.test import APIClient

        register = self.client.post('/api/guest/register/', {
            'store_token': self.store_token, 'phone': '09012345678', 'birthday_md': '03-07', 'consent': True,
        }, format='json')
        token = register.data['card_token']

        # A fresh browser (no cookie) presenting the right token gets the card.
        ok = APIClient().get('/api/guest/card/', HTTP_X_GUEST_TOKEN=token)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.data['points_balance'], 0)

        wrong = APIClient().get('/api/guest/card/', HTTP_X_GUEST_TOKEN='someone-elses-token')
        self.assertEqual(wrong.status_code, 404)

        missing = APIClient().get('/api/guest/card/')
        self.assertEqual(missing.status_code, 404)

    def test_card_pulse_returns_just_the_counters(self):
        from rest_framework.test import APIClient

        reg = self.client.post('/api/guest/register/', {
            'store_token': self.store_token, 'phone': '09012345678', 'birthday_md': '03-07', 'consent': True,
        }, format='json')
        token = reg.data['card_token']

        pulse = APIClient().get('/api/guest/card/pulse/', HTTP_X_GUEST_TOKEN=token)
        self.assertEqual(pulse.status_code, 200)
        self.assertEqual(
            set(pulse.data),
            {'points_balance', 'lifetime_points', 'stamp_count', 'draw_chances', 'voucher_count'},
        )
        self.assertNotIn('card_token', pulse.data)
        self.assertEqual(APIClient().get('/api/guest/card/pulse/').status_code, 404)

    def test_prizes_endpoint_lists_names_and_types_no_weights(self):
        from rest_framework.test import APIClient

        make_prize(self.campaign, weight=1, reward_type=RewardType.DRINK, name='ドリンク')
        make_prize(self.campaign, weight=3, reward_type=RewardType.CASH_VOUCHER,
                   config={'face_yen': 500}, name='¥500券', total_stock=0, remaining_stock=0)
        reg = self.client.post('/api/guest/register/', {
            'store_token': self.store_token, 'phone': '09012345678', 'birthday_md': '03-07', 'consent': True,
        }, format='json')
        rows = APIClient().get('/api/guest/prizes/', HTTP_X_GUEST_TOKEN=reg.data['card_token'])
        self.assertEqual(rows.status_code, 200)
        self.assertEqual({r['name'] for r in rows.data}, {'ドリンク', '¥500券'})
        self.assertTrue(all('weight' not in r for r in rows.data))
        sold = next(r for r in rows.data if r['name'] == '¥500券')
        self.assertTrue(sold['sold_out'])

    def test_readonly_login_by_phone_and_birthday(self):
        self.client.post('/api/guest/register/', {
            'store_token': self.store_token, 'phone': '09012345678', 'birthday_md': '03-07', 'consent': True,
        }, format='json')
        ok = self.client.post('/api/guest/login/', {'phone': '090-1234-5678', 'birthday_md': '3/7'}, format='json')
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(ok.data['readonly'])

        wrong = self.client.post('/api/guest/login/', {'phone': '09012345678', 'birthday_md': '01-01'}, format='json')
        self.assertEqual(wrong.status_code, 400)

    def test_readonly_login_never_hands_back_the_card_token(self):
        # phone + birthday is a weak second factor (打卡与抽奖实施方案.md
        # §14): the recovery snapshot can be viewed, never spent from, so it
        # must not carry the bearer credential.
        self.client.post('/api/guest/register/', {
            'store_token': self.store_token, 'phone': '09012345678', 'birthday_md': '03-07', 'consent': True,
        }, format='json')
        ok = self.client.post('/api/guest/login/', {'phone': '09012345678', 'birthday_md': '03-07'}, format='json')
        self.assertEqual(ok.status_code, 200)
        self.assertNotIn('card_token', ok.data)
        self.assertNotIn('pc_guest', ok.cookies)


class PinRecoveryTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        from django.core.cache import cache

        cache.clear()  # per-phone PIN failure counters live here
        self.campaign = make_campaign(self.branch_a)
        self.store_token = make_store_token(self.campaign)

    def _register(self, phone='09012345678', pin='481902', birthday_md='03-07', **extra):
        body = {'store_token': self.store_token, 'phone': phone,
                'birthday_md': birthday_md, 'consent': True}
        body.update(extra)
        if pin is not None:
            body['pin'] = pin
        return self.client.post('/api/guest/register/', body, format='json')

    def _recover(self, pin, phone='09012345678', birthday_md='03-07', client=None, **extra):
        body = {'phone': phone, 'birthday_md': birthday_md, 'pin': pin}
        body.update(extra)
        return (client or self.client).post('/api/guest/recover/', body, format='json')

    def test_register_with_pin_then_recover_full_access(self):
        reg = self._register(pin='481902')
        self.assertEqual(reg.status_code, 201, reg.content)
        token = reg.data['card_token']

        from rest_framework.test import APIClient
        rec = self._recover('481902', phone='090-1234-5678', client=APIClient())  # new device
        self.assertEqual(rec.status_code, 200, rec.content)
        self.assertEqual(rec.data['card_token'], token)
        self.assertIn('pc_guest', rec.cookies)

    def test_recover_rejects_wrong_pin_without_an_oracle(self):
        self._register(pin='481902')
        bad = self._recover('999000')
        self.assertEqual(bad.status_code, 400)
        self.assertNotIn('card_token', bad.data)
        # same generic error for a phone that was never registered
        unknown = self._recover('481902', phone='08000000000')
        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(str(bad.data), str(unknown.data))

    def test_recover_needs_a_pin_to_have_been_set(self):
        self._register(pin=None)  # registered without a PIN
        self.assertEqual(self._recover('481902').status_code, 400)

    def test_five_wrong_tries_locks_the_phone_and_flags_it(self):
        self._register(pin='481902')
        for _ in range(5):
            self._recover('000001')
        locked = self._recover('481902')  # even the correct PIN is now refused
        self.assertEqual(locked.status_code, 400)
        self.assertIn('pin-recovery-locked', str(locked.data))
        self.assertTrue(
            RiskEvent.objects.filter(event_type=RiskEvent.EventType.PIN_RECOVERY_LOCKOUT).exists()
        )

    def test_weak_pins_are_rejected(self):
        for weak in ('123456', '111111', '000000'):
            resp = self._register(phone='09012345678', pin=weak)
            self.assertEqual(resp.status_code, 400, weak)
            self.assertFalse(Customer.objects.filter(phone='09012345678').exists())

    def test_set_pin_requires_the_guest_token_then_enables_recovery(self):
        reg = self._register(pin=None)
        token = reg.data['card_token']

        from rest_framework.test import APIClient
        anon = APIClient()
        self.assertEqual(
            anon.post('/api/guest/set-pin/', {'pin': '481902'}, format='json').status_code, 404,
        )

        holder = APIClient()
        holder.credentials(HTTP_X_GUEST_TOKEN=token)
        self.assertEqual(
            holder.post('/api/guest/set-pin/', {'pin': '481902'}, format='json').status_code, 200,
        )
        self.assertEqual(self._recover('481902').data['card_token'], token)

    def test_a_stranger_cannot_set_a_pin_on_an_existing_card(self):
        self._register(pin='481902')
        # register again with the same phone -> existing, no token, PIN untouched
        again = self._register(phone='09012345678', pin='222444')
        self.assertEqual(again.status_code, 200)
        self.assertTrue(again.data.get('existing'))
        # the stranger's PIN did not take: the original still recovers
        self.assertEqual(self._recover('481902').status_code, 200)


# ---------------------------------------------------------------------------
# Staff / admin API
# ---------------------------------------------------------------------------

class SpendVerificationApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.campaign = make_campaign(self.branch_a)
        self.customer = register_customer(organization=self.org, phone='09011112222', name='田中')

    def test_staff_confirms_spend_and_points_are_granted(self):
        self.login_as(self.staff_user)
        resp = self.client.post('/api/promotions/spend-verifications/', {
            'card_token': self.customer.card_token, 'amount_yen': 4200,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        # ¥4,200 -> floor(4200/1000) * 10 = 40 (the sub-¥1,000 remainder
        # never earns — spec is `amount_yen // 1000 * rate`).
        self.assertEqual(resp.data['points_granted'], 40)
        self.assertEqual(resp.data['points_balance'], 40)
        self.assertEqual(SpendVerification.objects.get().verified_by, self.staff_user)

    def test_staff_lookup_returns_masked_phone_only(self):
        self.login_as(self.staff_user)
        resp = self.client.post('/api/promotions/customers/lookup/', {
            'card_token': self.customer.card_token,
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['phone_masked'], '••••2222')
        self.assertNotIn('phone', resp.data)
        self.assertNotIn('card_token', resp.data)

    def test_public_spend_verification_endpoint_needs_auth(self):
        resp = self.client.post('/api/promotions/spend-verifications/', {
            'card_token': self.customer.card_token, 'amount_yen': 4200,
        }, format='json')
        self.assertEqual(resp.status_code, 401)

    def test_staff_cannot_list_campaigns_or_adjust_points_or_void(self):
        self.login_as(self.staff_user)
        self.assertEqual(self.client.get('/api/promotions/campaigns/').status_code, 403)
        adjust = self.client.post(
            f'/api/promotions/customers/{self.customer.id}/points-adjust/',
            {'delta': 10, 'note': 'x'}, format='json',
        )
        self.assertEqual(adjust.status_code, 403)
        self.assertEqual(self.client.get('/api/promotions/spend-verifications/').status_code, 403)

    def test_staff_mine_lists_only_own_confirmations(self):
        self.login_as(self.staff_user)
        self.client.post('/api/promotions/spend-verifications/', {
            'card_token': self.customer.card_token, 'amount_yen': 2000,
        }, format='json')
        resp = self.client.get('/api/promotions/spend-verifications/mine/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)

    def test_spend_verification_is_append_only(self):
        v = verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                         amount_yen=2000, verified_by=self.staff_user)
        self.login_as(self.admin)
        self.assertEqual(
            self.client.patch(f'/api/promotions/spend-verifications/{v.id}/', {'amount_yen': 1}, format='json').status_code,
            405,
        )
        self.assertEqual(
            self.client.delete(f'/api/promotions/spend-verifications/{v.id}/').status_code, 405,
        )

    def test_admin_void_reverses_points(self):
        v = verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                         amount_yen=5000, verified_by=self.staff_user)
        self.login_as(self.admin)
        resp = self.client.post(f'/api/promotions/spend-verifications/{v.id}/void/', {'reason': 'mistake'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.points_balance, 0)

    def test_branch_cannot_void(self):
        v = verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                         amount_yen=5000, verified_by=self.staff_user)
        self.login_as(self.branch_a_user)
        resp = self.client.post(f'/api/promotions/spend-verifications/{v.id}/void/', {'reason': 'x'}, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_branch_only_sees_own_branch_verifications(self):
        other_campaign = make_campaign(self.branch_b)
        other_customer = register_customer(organization=self.org, phone='09099998888')
        verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                     amount_yen=2000, verified_by=self.staff_user)
        verify_spend(campaign=other_campaign, branch=self.branch_b, customer=other_customer,
                     amount_yen=2000, verified_by=self.admin)
        self.login_as(self.branch_a_user)
        resp = self.client.get('/api/promotions/spend-verifications/')
        self.assertEqual(resp.data['count'], 1)

    def test_admin_points_adjust_and_customer_delete(self):
        self.login_as(self.admin)
        adjust = self.client.post(
            f'/api/promotions/customers/{self.customer.id}/points-adjust/',
            {'delta': 120, 'note': 'launch bonus'}, format='json',
        )
        self.assertEqual(adjust.status_code, 201, adjust.content)
        self.assertEqual(adjust.data['points_balance'], 120)

        delete = self.client.delete(f'/api/promotions/customers/{self.customer.id}/')
        self.assertEqual(delete.status_code, 200)
        self.assertFalse(Customer.objects.filter(id=self.customer.id).exists())

    def test_campaign_crud_for_branch_account(self):
        self.login_as(self.branch_a_user)
        create = self.client.post('/api/promotions/campaigns/', {
            'name': '夏祭りキャンペーン', 'status': 'active', 'points_per_1000yen': 10, 'stamp_target': 5,
        }, format='json')
        self.assertEqual(create.status_code, 201, create.content)
        self.assertEqual(create.data['branch'], self.branch_a.id)
        self.assertTrue(create.data['store_token'])


class CrossOrganizationIsolationTests(TwoOrganizationApiTestCase):
    def setUp(self):
        super().setUp()
        self.campaign_a = Campaign.objects.create(
            branch=self.branch_a1, name='A社カード', status=Campaign.Status.ACTIVE,
        )
        self.customer_a = register_customer(organization=self.org_a, phone='09011112222', name='A客')

    def test_staff_lookup_scoped_to_own_organization(self):
        self.login_as(self.staff_user_a1)
        # org A staff can find org A's customer
        ok = self.client.post('/api/promotions/customers/lookup/', {
            'card_token': self.customer_a.card_token,
        }, format='json')
        self.assertEqual(ok.status_code, 200)

        self.login_as(self.branch_b1_user)
        miss = self.client.post('/api/promotions/customers/lookup/', {
            'card_token': self.customer_a.card_token,
        }, format='json')
        self.assertEqual(miss.status_code, 404)

    def test_admin_cannot_delete_another_organizations_customer(self):
        self.login_as(self.admin_b)
        resp = self.client.delete(f'/api/promotions/customers/{self.customer_a.id}/')
        self.assertIn(resp.status_code, (403, 404))
        self.assertTrue(Customer.objects.filter(id=self.customer_a.id).exists())

    def test_spend_verification_cannot_cross_into_another_org(self):
        self.login_as(self.admin_b)
        resp = self.client.post('/api/promotions/spend-verifications/', {
            'branch': self.branch_a1.id, 'card_token': self.customer_a.card_token, 'amount_yen': 2000,
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(SpendVerification.objects.count(), 0)

    def test_voucher_from_another_org_cannot_be_verified_or_redeemed(self):
        adjust_points(customer=self.customer_a, delta=500, note='seed', operator=self.admin_a)
        make_prize(self.campaign_a, weight=1, reward_type=RewardType.CASH_VOUCHER, config={'face_yen': 500})
        draw = draw_lottery(campaign=self.campaign_a, branch=self.branch_a1, customer=self.customer_a,
                            source='points', request_id='x')
        code = draw.vouchers.first().redemption_code

        self.login_as(self.admin_b)
        self.assertEqual(
            self.client.post('/api/promotions/vouchers/verify/', {'redemption_code': code}, format='json').status_code,
            404,
        )
        self.assertEqual(
            self.client.post('/api/promotions/vouchers/redeem/', {'redemption_code': code}, format='json').status_code,
            404,
        )

    def test_guest_recovery_disambiguates_when_phone_is_at_two_chains(self):
        # Same person, same phone + birthday + PIN, registered at two
        # separate chains -> recovery returns a "which card?" picker, then
        # the chosen org resolves to exactly one card.
        campaign_b = Campaign.objects.create(
            branch=self.branch_b1, name='B社カード', status=Campaign.Status.ACTIVE,
        )
        cust_a = register_customer(organization=self.org_a, phone='08099998888',
                                   birthday_md='03-07', pin='481902', campaign=self.campaign_a)
        register_customer(organization=self.org_b, phone='08099998888',
                          birthday_md='03-07', pin='481902', campaign=campaign_b)

        login = self.client.post('/api/guest/login/',
                                 {'phone': '08099998888', 'birthday_md': '03-07'}, format='json')
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.data['multiple'])
        self.assertEqual(len(login.data['options']), 2)

        recover = self.client.post(
            '/api/guest/recover/',
            {'phone': '08099998888', 'birthday_md': '03-07', 'pin': '481902'}, format='json',
        )
        self.assertEqual(recover.status_code, 200)
        self.assertTrue(recover.data['multiple'])

        # picking a chain resolves to exactly that card
        picked = self.client.post(
            '/api/guest/recover/',
            {'phone': '08099998888', 'birthday_md': '03-07', 'pin': '481902',
             'org': str(self.org_a.id)},
            format='json',
        )
        self.assertEqual(picked.status_code, 200)
        self.assertEqual(picked.data['card_token'], cust_a.card_token)

        # a phone unique to one org recovers straight away
        register_customer(organization=self.org_a, phone='08011112222',
                          birthday_md='05-05', pin='728364', campaign=self.campaign_a)
        ok = self.client.post(
            '/api/guest/recover/',
            {'phone': '08011112222', 'birthday_md': '05-05', 'pin': '728364'}, format='json',
        )
        self.assertEqual(ok.status_code, 200)
        self.assertIn('card_token', ok.data)


# ===========================================================================
# Phase 2 / 2.5 — lottery, prizes, vouchers, milestones
# ===========================================================================

class DrawLotteryServiceTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.campaign = make_campaign(self.branch_a, points_per_draw=100, direct_draw_threshold_yen=3000)
        self.customer = register_customer(organization=self.org, phone='09011112222', name='田中')
        adjust_points(customer=self.customer, delta=1000, note='seed', operator=self.admin)
        self.customer.refresh_from_db()

    def test_points_draw_spends_points_and_snapshots_weight(self):
        make_prize(self.campaign, weight=1, reward_type=RewardType.DRINK)
        draw = draw_lottery(
            campaign=self.campaign, branch=self.branch_a, customer=self.customer,
            source='points', request_id='r1',
        )
        self.customer.refresh_from_db()
        self.assertEqual(draw.status, LotteryDraw.Status.WON)
        self.assertEqual(draw.points_spent, 100)
        self.assertEqual(draw.weight_snapshot, 1)
        self.assertEqual(draw.total_weight_snapshot, 1)
        self.assertEqual(self.customer.points_balance, 900)
        self.assertEqual(self.customer.vouchers.count(), 1)
        # ledger stays consistent
        self.assertEqual(
            sum(self.customer.points_ledger.values_list('delta', flat=True)),
            self.customer.points_balance,
        )

    def test_points_refund_prize_returns_points_no_voucher(self):
        make_prize(self.campaign, weight=1, reward_type=RewardType.POINTS_REFUND, config={'points': 30})
        draw = draw_lottery(
            campaign=self.campaign, branch=self.branch_a, customer=self.customer,
            source='points', request_id='r1',
        )
        self.customer.refresh_from_db()
        self.assertEqual(draw.status, LotteryDraw.Status.REFUND)
        self.assertEqual(draw.points_refunded, 30)
        self.assertEqual(self.customer.points_balance, 1000 - 100 + 30)
        self.assertEqual(self.customer.vouchers.count(), 0)

    def test_draw_is_idempotent_on_request_id(self):
        make_prize(self.campaign, weight=1)
        d1 = draw_lottery(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                          source='points', request_id='same')
        d2 = draw_lottery(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                          source='points', request_id='same')
        self.assertEqual(d1.id, d2.id)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.points_balance, 900)  # charged once

    def test_insufficient_points_rejected(self):
        make_prize(self.campaign, weight=1)
        self.customer.points_balance = 50
        self.customer.save(update_fields=['points_balance'])
        with self.assertRaises(ValidationError):
            draw_lottery(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                         source='points', request_id='r1')
        self.assertEqual(LotteryDraw.objects.count(), 0)

    def test_direct_draw_uses_a_chance_from_a_qualifying_spend(self):
        make_prize(self.campaign, weight=1)
        verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                     amount_yen=3500, verified_by=self.staff_user)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.draw_chances, 1)

        draw_lottery(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                     source='direct', request_id='r1')
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.draw_chances, 0)
        with self.assertRaises(ValidationError):
            draw_lottery(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                         source='direct', request_id='r2')

    def test_stock_limits_cap_how_many_times_a_prize_can_be_won(self):
        rare = make_prize(self.campaign, weight=1, reward_type=RewardType.CASH_VOUCHER,
                          config={'face_yen': 500}, total_stock=2, remaining_stock=2)
        common = make_prize(self.campaign, weight=1, reward_type=RewardType.DRINK)
        adjust_points(customer=self.customer, delta=10000, note='x', operator=self.admin)
        self.campaign.max_draws_per_customer_per_day = None
        self.campaign.save(update_fields=['max_draws_per_customer_per_day'])

        for i in range(8):
            draw_lottery(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                         source='points', request_id=f'd{i}')

        self.assertLessEqual(LotteryDraw.objects.filter(prize=rare).count(), 2)
        rare.refresh_from_db()
        self.assertEqual(rare.remaining_stock, 2 - LotteryDraw.objects.filter(prize=rare).count())
        # once rare is exhausted, `common` is the only option left
        self.assertGreaterEqual(LotteryDraw.objects.filter(prize=common).count(), 6)
        self.assertEqual(
            LotteryDraw.objects.filter(prize__in=[rare, common]).count(), 8,
        )

    def test_daily_stock_cap_removes_a_prize_for_the_day(self):
        capped = only_prize(self.campaign, weight=1, reward_type=RewardType.DRINK, daily_stock=1)
        adjust_points(customer=self.customer, delta=10000, note='x', operator=self.admin)
        self.campaign.max_draws_per_customer_per_day = None
        self.campaign.save(update_fields=['max_draws_per_customer_per_day'])

        first = draw_lottery(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                             source='points', request_id='a')
        self.assertEqual(first.prize_id, capped.id)
        with self.assertRaises(ValidationError):
            draw_lottery(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                         source='points', request_id='b')

    def test_daily_draw_cap_enforced(self):
        make_prize(self.campaign, weight=1)
        self.campaign.max_draws_per_customer_per_day = 2
        self.campaign.save(update_fields=['max_draws_per_customer_per_day'])
        adjust_points(customer=self.customer, delta=10000, note='x', operator=self.admin)
        draw_lottery(campaign=self.campaign, branch=self.branch_a, customer=self.customer, source='points', request_id='a')
        draw_lottery(campaign=self.campaign, branch=self.branch_a, customer=self.customer, source='points', request_id='b')
        with self.assertRaises(ValidationError):
            draw_lottery(campaign=self.campaign, branch=self.branch_a, customer=self.customer, source='points', request_id='c')


class MilestoneTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.campaign = make_campaign(self.branch_a)
        Milestone.objects.create(campaign=self.campaign, points_threshold=300,
                                 reward_type=RewardType.DRINK, reward_config={'label': 'drink'})
        Milestone.objects.create(campaign=self.campaign, points_threshold=800,
                                 reward_type=RewardType.CASH_VOUCHER, reward_config={'face_yen': 500})
        self.customer = register_customer(organization=self.org, phone='09011112222')

    def test_milestone_voucher_issued_once_when_lifetime_crosses(self):
        # ¥25,000 -> 250 pts: below 300, nothing yet
        verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                     amount_yen=25000, verified_by=self.staff_user)
        self.assertEqual(self.customer.vouchers.count(), 0)

        # +¥10,000 -> +100 pts -> lifetime 350: crosses 300 only
        verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                     amount_yen=10000, verified_by=self.staff_user)
        self.assertEqual(MilestoneClaim.objects.filter(customer=self.customer).count(), 1)
        self.assertEqual(self.customer.vouchers.filter(source=Voucher.Source.MILESTONE).count(), 1)

        # a later big spend crossing 800 issues the second, not a duplicate of the first
        verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                     amount_yen=50000, verified_by=self.staff_user)
        self.assertEqual(MilestoneClaim.objects.filter(customer=self.customer).count(), 2)

    def test_void_lowers_lifetime_but_keeps_issued_milestone_voucher(self):
        v = verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                         amount_yen=35000, verified_by=self.staff_user)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.lifetime_points_earned, 350)
        self.assertEqual(self.customer.vouchers.count(), 1)

        void_spend_verification(verification=v, operator=self.admin, reason='mistake')
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.lifetime_points_earned, 0)
        # the voucher already handed out is not clawed back
        self.assertEqual(self.customer.vouchers.count(), 1)
        self.assertEqual(MilestoneClaim.objects.filter(customer=self.customer).count(), 1)


class RedeemVoucherTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.campaign = make_campaign(self.branch_a, points_per_voucher=100, voucher_yen_per_unit=100)
        self.customer = register_customer(organization=self.org, phone='09011112222')
        adjust_points(customer=self.customer, delta=500, note='seed', operator=self.admin)
        self.customer.refresh_from_db()

    def _issue_min_spend_voucher(self, min_spend, approval=False):
        prize = make_prize(self.campaign, weight=1, reward_type=RewardType.CASH_VOUCHER,
                           config={'face_yen': 1000}, voucher_min_spend_yen=min_spend,
                           requires_manual_approval=approval)
        draw = draw_lottery(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                            source='points', request_id='v1')
        return draw.vouchers.first()

    def test_min_spend_gate(self):
        voucher = self._issue_min_spend_voucher(3000)
        with self.assertRaises(ValidationError):
            redeem_voucher(voucher=voucher, branch=self.branch_a, operator=self.staff_user,
                           spend_amount_yen=2000)
        redeemed = redeem_voucher(voucher=voucher, branch=self.branch_a, operator=self.staff_user,
                                  spend_amount_yen=3500)
        self.assertEqual(redeemed.status, Voucher.Status.REDEEMED)

    def test_expired_voucher_rejected(self):
        voucher = self._issue_min_spend_voucher(0)
        voucher.expires_at = timezone.now() - timedelta(days=1)
        voucher.save(update_fields=['expires_at'])
        with self.assertRaises(ValidationError):
            redeem_voucher(voucher=voucher, branch=self.branch_a, operator=self.staff_user)
        voucher.refresh_from_db()
        self.assertEqual(voucher.status, Voucher.Status.EXPIRED)

    def test_manager_approval_required_for_top_prize(self):
        voucher = self._issue_min_spend_voucher(0, approval=True)
        with self.assertRaises(ValidationError):
            redeem_voucher(voucher=voucher, branch=self.branch_a, operator=self.staff_user)
        ok = redeem_voucher(voucher=voucher, branch=self.branch_a, operator=self.staff_user,
                            approved_by=self.branch_a_user)
        self.assertEqual(ok.approved_by, self.branch_a_user)

    def test_same_org_cross_branch_redemption_is_allowed(self):
        # A card works across the whole chain — a voucher won at branch A
        # redeems at branch B of the same Organization.
        voucher = self._issue_min_spend_voucher(0)
        done = redeem_voucher(voucher=voucher, branch=self.branch_b, operator=self.staff_user)
        self.assertEqual(done.status, Voucher.Status.REDEEMED)
        self.assertEqual(done.redeemed_branch, self.branch_b)


class ExpirePointsTests(ApiTestCase):
    def test_stale_balance_is_zeroed_and_logged(self):
        campaign = make_campaign(self.branch_a, points_expire_months=12)
        customer = register_customer(organization=self.org, phone='09011112222', campaign=campaign)
        adjust_points(customer=customer, delta=250, note='seed', operator=self.admin)
        customer.refresh_from_db()

        # still fresh -> untouched
        expire_stale_points()
        customer.refresh_from_db()
        self.assertEqual(customer.points_balance, 250)

        Customer.objects.filter(pk=customer.pk).update(
            last_activity_at=timezone.now() - timedelta(days=400),
        )
        result = expire_stale_points()
        customer.refresh_from_db()
        self.assertEqual(customer.points_balance, 0)
        self.assertEqual(result['points'], 250)
        self.assertTrue(
            customer.points_ledger.filter(reason=PointsLedger.Reason.EXPIRE, delta=-250).exists()
        )


class Phase2ApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.campaign = make_campaign(self.branch_a, points_per_draw=100, points_per_voucher=100,
                                      voucher_yen_per_unit=100)
        make_prize(self.campaign, weight=1, reward_type=RewardType.DRINK)
        self.store_token = make_store_token(self.campaign)
        self.customer = register_customer(organization=self.org, phone='09012345678',
                                          birthday_md='03-07', campaign=self.campaign)
        adjust_points(customer=self.customer, delta=500, note='seed', operator=self.admin)

    def _guest(self):
        from rest_framework.test import APIClient
        client = APIClient()
        client.credentials(HTTP_X_GUEST_TOKEN=self.customer.card_token)
        return client

    def test_guest_redeem_draw_and_voucher(self):
        client = self._guest()
        draw = client.post('/api/guest/redeem/', {'type': 'draw', 'request_id': 'g1'}, format='json')
        self.assertEqual(draw.status_code, 201, draw.content)
        self.assertEqual(draw.data['points_balance'], 400)
        self.assertIn('result', draw.data)

        voucher = client.post('/api/guest/redeem/', {'type': 'voucher', 'request_id': 'g2'}, format='json')
        self.assertEqual(voucher.status_code, 201)
        self.assertEqual(voucher.data['points_balance'], 300)
        self.assertIn('redemption_code', voucher.data['voucher'])

        # idempotent
        again = client.post('/api/guest/redeem/', {'type': 'draw', 'request_id': 'g1'}, format='json')
        self.assertEqual(again.data['points_balance'], 300)

    def test_guest_cannot_replay_another_customers_request_id(self):
        # request_id is a per-customer idempotency key. Replaying someone
        # else's id must never echo back their draw / voucher code.
        alice = self._guest()
        won = alice.post('/api/guest/redeem/', {'type': 'draw', 'request_id': 'shared-id'}, format='json')
        self.assertEqual(won.status_code, 201, won.content)
        alice_code = won.data['result']['voucher']['redemption_code']

        mallory_customer = register_customer(
            organization=self.org, phone='08099998888', campaign=self.campaign,
        )
        adjust_points(customer=mallory_customer, delta=500, note='seed', operator=self.admin)
        from rest_framework.test import APIClient
        mallory = APIClient()
        mallory.credentials(HTTP_X_GUEST_TOKEN=mallory_customer.card_token)

        replay = mallory.post(
            '/api/guest/redeem/', {'type': 'draw', 'request_id': 'shared-id'}, format='json',
        )
        self.assertEqual(replay.status_code, 400)
        self.assertNotIn(alice_code, replay.content.decode())
        # Mallory was not charged for the rejected replay.
        mallory_customer.refresh_from_db()
        self.assertEqual(mallory_customer.points_balance, 500)

    def test_guest_card_lists_active_vouchers(self):
        self._guest().post('/api/guest/redeem/', {'type': 'voucher', 'request_id': 'g1'}, format='json')
        card = self._guest().get('/api/guest/card/')
        self.assertEqual(len(card.data['vouchers']), 1)
        self.assertEqual(card.data['lifetime_points'], 0)

    def test_public_redeem_rejects_forged_points(self):
        client = self._guest()
        resp = client.post('/api/guest/redeem/', {
            'type': 'voucher', 'request_id': 'g1', 'points_balance': 99999, 'face_yen': 99999,
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        voucher = Voucher.objects.get()
        self.assertEqual(voucher.config_snapshot.get('face_yen'), 100)

    def test_staff_voucher_verify_and_redeem(self):
        redeem = redeem_points(customer=self.customer, campaign=self.campaign, kind='voucher', request_id='x')
        code = redeem['voucher'].redemption_code

        self.login_as(self.staff_user)
        verify = self.client.post('/api/promotions/vouchers/verify/', {'redemption_code': code}, format='json')
        self.assertEqual(verify.status_code, 200)
        self.assertTrue(verify.data[0]['redeemable'])

        done = self.client.post('/api/promotions/vouchers/redeem/', {'redemption_code': code}, format='json')
        self.assertEqual(done.status_code, 200, done.content)
        self.assertEqual(done.data['status'], 'redeemed')

    def test_guest_self_serve_redeem_low_value_only(self):
        only_prize(self.campaign, weight=1, reward_type=RewardType.DESSERT, name='デザート')
        draw = draw_lottery(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                            source='points', request_id='d')
        code = draw.vouchers.first().redemption_code

        ok = self._guest().post('/api/guest/voucher/redeem/', {'redemption_code': code}, format='json')
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(ok.data['status'], 'redeemed')
        v = Voucher.objects.get(redemption_code=code)
        self.assertIsNone(v.redeemed_by_id)          # self-serve marker
        self.assertIsNotNone(v.redeemed_at)

        # a second slide is refused
        again = self._guest().post('/api/guest/voucher/redeem/', {'redemption_code': code}, format='json')
        self.assertEqual(again.status_code, 400)

    def test_guest_self_serve_refuses_cash_voucher(self):
        only_prize(self.campaign, weight=1, reward_type=RewardType.CASH_VOUCHER,
                   config={'face_yen': 500}, name='¥500券')
        draw = draw_lottery(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                            source='points', request_id='d')
        code = draw.vouchers.first().redemption_code
        resp = self._guest().post('/api/guest/voucher/redeem/', {'redemption_code': code}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('voucher-needs-staff', str(resp.data))
        self.assertEqual(Voucher.objects.get(redemption_code=code).status, 'active')

    def test_staff_voucher_lookup_by_name_and_phone_tail(self):
        self.customer.name = '田中花子'
        self.customer.save(update_fields=['name'])
        redeem_points(customer=self.customer, campaign=self.campaign, kind='voucher', request_id='v')

        self.login_as(self.staff_user)
        by_name = self.client.post(
            '/api/promotions/vouchers/verify/', {'name': '田中', 'phone_tail': '5678'}, format='json',
        )
        self.assertEqual(by_name.status_code, 200, by_name.content)
        self.assertEqual(by_name.data[0]['customer_name'], '田中花子')

        miss = self.client.post(
            '/api/promotions/vouchers/verify/', {'name': '田中', 'phone_tail': '0000'}, format='json',
        )
        self.assertEqual(miss.status_code, 404)

    def test_guest_cannot_self_serve_another_customers_voucher(self):
        only_prize(self.campaign, weight=1, reward_type=RewardType.DRINK, name='ドリンク')
        other = register_customer(organization=self.org, phone='08000000000', campaign=self.campaign)
        other.draw_chances = 1
        other.save(update_fields=['draw_chances'])
        draw = draw_lottery(campaign=self.campaign, branch=self.branch_a, customer=other,
                            source='direct', request_id='d')
        code = draw.vouchers.first().redemption_code
        resp = self._guest().post('/api/guest/voucher/redeem/', {'redemption_code': code}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Voucher.objects.get(redemption_code=code).status, 'active')

    def test_staff_cannot_redeem_approval_required_voucher(self):
        only_prize(self.campaign, weight=1, reward_type=RewardType.CASH_VOUCHER,
                   config={'face_yen': 5000}, requires_manual_approval=True)
        draw = draw_lottery(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                            source='points', request_id='top')
        code = draw.vouchers.first().redemption_code

        self.login_as(self.staff_user)
        resp = self.client.post('/api/promotions/vouchers/redeem/', {'redemption_code': code}, format='json')
        self.assertEqual(resp.status_code, 403)

        self.login_as(self.branch_a_user)
        ok = self.client.post('/api/promotions/vouchers/redeem/', {
            'redemption_code': code, 'spend_amount_yen': 10000,
        }, format='json')
        self.assertEqual(ok.status_code, 200, ok.content)

    def test_prize_crud_and_probability(self):
        self.login_as(self.admin)
        resp = self.client.post('/api/promotions/prizes/', {
            'campaign': self.campaign.id, 'name': 'デザート', 'weight': 3,
            'reward_type': 'dessert', 'reward_config': {'label': 'ケーキ'},
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        listing = self.client.get(f'/api/promotions/prizes/?campaign={self.campaign.id}')
        self.assertEqual(len(listing.data), 2)
        self.assertAlmostEqual(sum(p['probability'] for p in listing.data), 1.0, places=3)

    def test_prize_reward_config_validated_by_type(self):
        self.login_as(self.admin)
        bad = self.client.post('/api/promotions/prizes/', {
            'campaign': self.campaign.id, 'name': 'x', 'weight': 1,
            'reward_type': 'cash_voucher', 'reward_config': {},
        }, format='json')
        self.assertEqual(bad.status_code, 400)
        self.assertIn('face_yen', str(bad.data))

    def test_limited_prize_gets_remaining_stock_on_create_and_edit(self):
        self.login_as(self.admin)
        made = self.client.post('/api/promotions/prizes/', {
            'campaign': self.campaign.id, 'name': '限定', 'weight': 1,
            'reward_type': 'drink', 'total_stock': 10,
        }, format='json')
        self.assertEqual(made.status_code, 201, made.content)
        prize = Prize.objects.get(pk=made.data['id'])
        self.assertEqual(prize.remaining_stock, 10)

        # consume 3, then admin raises the cap to 20 -> remaining tracks it
        Prize.objects.filter(pk=prize.pk).update(remaining_stock=7)
        self.client.patch(f'/api/promotions/prizes/{prize.pk}/', {'total_stock': 20}, format='json')
        prize.refresh_from_db()
        self.assertEqual(prize.remaining_stock, 17)  # 20 - 3 consumed

        # switching to unlimited clears the cap
        self.client.patch(f'/api/promotions/prizes/{prize.pk}/', {'total_stock': None}, format='json')
        prize.refresh_from_db()
        self.assertIsNone(prize.remaining_stock)

    def test_prize_writes_are_admin_only_branch_reads(self):
        # §15 decision 09 — prize economics is chain-level.
        self.login_as(self.branch_a_user)
        self.assertEqual(
            self.client.get(f'/api/promotions/prizes/?campaign={self.campaign.id}').status_code, 200,
        )
        blocked = self.client.post('/api/promotions/prizes/', {
            'campaign': self.campaign.id, 'name': 'x', 'weight': 1,
            'reward_type': 'drink', 'reward_config': {},
        }, format='json')
        self.assertEqual(blocked.status_code, 403)

    def test_staff_blocked_from_prize_management(self):
        self.login_as(self.staff_user)
        self.assertEqual(self.client.get('/api/promotions/prizes/').status_code, 403)
        self.assertEqual(self.client.get('/api/promotions/milestones/').status_code, 403)

    def test_campaign_draws_and_vouchers_records(self):
        redeem_points(customer=self.customer, campaign=self.campaign, kind='draw', request_id='d1')
        self.login_as(self.admin)
        draws = self.client.get(f'/api/promotions/campaigns/{self.campaign.id}/draws/')
        self.assertEqual(draws.data['count'], 1)
        vouchers = self.client.get(f'/api/promotions/campaigns/{self.campaign.id}/vouchers/')
        self.assertEqual(vouchers.data['count'], 1)


# ===========================================================================
# Phase 3 — anti-fraud, permissions, retention, reports
# ===========================================================================

class RiskRuleTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.campaign = make_campaign(self.branch_a, direct_draw_threshold_yen=3000)
        self.customer = register_customer(organization=self.org, phone='09011112222', name='田中')

    def test_off_hours_confirmation_is_flagged_low(self):
        # The most recent 05:00 local — always in the past (so verify_spend
        # accepts it) and always an "off-hours" time. A bare replace(hour=5)
        # would land in the future when the suite runs before 05:00.
        now_local = timezone.localtime(timezone.now())
        early = now_local.replace(hour=5, minute=0, second=0, microsecond=0)
        if early > now_local:
            early -= timedelta(days=1)
        verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                     amount_yen=2000, consumed_at=early, verified_by=self.staff_user)
        ev = RiskEvent.objects.filter(event_type=RiskEvent.EventType.OFF_HOURS_VERIFICATION)
        self.assertEqual(ev.count(), 1)
        self.assertEqual(ev.first().severity, RiskEvent.Severity.LOW)

    def test_amount_exactly_equal_to_a_voucher_threshold_is_flagged(self):
        make_prize(self.campaign, weight=1, reward_type=RewardType.CASH_VOUCHER,
                   config={'face_yen': 500}, voucher_min_spend_yen=1500)
        verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                     amount_yen=1500, verified_by=self.staff_user)
        self.assertTrue(
            RiskEvent.objects.filter(event_type=RiskEvent.EventType.AMOUNT_EQUALS_THRESHOLD).exists()
        )
        # a non-threshold amount is not flagged
        verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                     amount_yen=1499, verified_by=self.staff_user)
        self.assertEqual(
            RiskEvent.objects.filter(event_type=RiskEvent.EventType.AMOUNT_EQUALS_THRESHOLD).count(), 1
        )

    def test_rapid_staff_confirmations_flagged_once_per_minute_bucket(self):
        others = [register_customer(organization=self.org, phone=f'0901111{i:04d}') for i in range(14)]
        for c in others:
            verify_spend(campaign=self.campaign, branch=self.branch_a, customer=c,
                         amount_yen=1000, verified_by=self.staff_user)
        self.assertGreaterEqual(
            RiskEvent.objects.filter(event_type=RiskEvent.EventType.STAFF_RAPID_VERIFICATIONS).count(), 1
        )

    def test_device_multi_register_flag(self):
        for i in range(3):
            register_customer(organization=self.org, phone=f'0908888{i:04d}', ip='203.0.113.9')
        self.assertTrue(
            RiskEvent.objects.filter(event_type=RiskEvent.EventType.DEVICE_MULTI_REGISTER).exists()
        )

    def test_rapid_draws_flag(self):
        only_prize(self.campaign, weight=1, reward_type=RewardType.DRINK)
        adjust_points(customer=self.customer, delta=10000, note='x', operator=self.admin)
        self.campaign.max_draws_per_customer_per_day = None
        self.campaign.save(update_fields=['max_draws_per_customer_per_day'])
        for i in range(4):
            draw_lottery(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                         source='points', request_id=f'r{i}')
        self.assertTrue(
            RiskEvent.objects.filter(event_type=RiskEvent.EventType.CUSTOMER_RAPID_DRAWS).exists()
        )

    def test_high_value_streak_flag(self):
        only_prize(self.campaign, weight=1, reward_type=RewardType.CASH_VOUCHER, config={'face_yen': 1000})
        adjust_points(customer=self.customer, delta=10000, note='x', operator=self.admin)
        self.campaign.max_draws_per_customer_per_day = None
        self.campaign.save(update_fields=['max_draws_per_customer_per_day'])
        for i in range(3):
            draw_lottery(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                         source='points', request_id=f'hv{i}')
        ev = RiskEvent.objects.filter(event_type=RiskEvent.EventType.HIGH_VALUE_PRIZE_STREAK)
        self.assertTrue(ev.exists())
        self.assertEqual(ev.first().severity, RiskEvent.Severity.HIGH)

    def test_void_after_redemption_flag(self):
        only_prize(self.campaign, weight=1, reward_type=RewardType.DRINK)
        v = verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                         amount_yen=20000, verified_by=self.staff_user)  # 200 pts
        draw = draw_lottery(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                            source='points', request_id='d1')
        redeem_voucher(voucher=draw.vouchers.first(), branch=self.branch_a, operator=self.staff_user)
        void_spend_verification(verification=v, operator=self.admin, reason='refunded')
        self.assertTrue(
            RiskEvent.objects.filter(event_type=RiskEvent.EventType.VOIDED_AFTER_REDEMPTION,
                                     severity=RiskEvent.Severity.HIGH).exists()
        )

    def test_a_broken_rule_never_breaks_the_checkout(self):
        import logging
        from unittest import mock
        logging.disable(logging.CRITICAL)
        try:
            with mock.patch('promotions.risk._record', side_effect=RuntimeError('boom')):
                v = verify_spend(campaign=self.campaign, branch=self.branch_a, customer=self.customer,
                                 amount_yen=2000, verified_by=self.staff_user)
        finally:
            logging.disable(logging.NOTSET)
        self.assertEqual(v.points_granted, 20)  # spend still succeeded


class RiskEventApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.campaign = make_campaign(self.branch_a)
        self.customer = register_customer(organization=self.org, phone='09011112222')
        self.event = RiskEvent.objects.create(
            organization=self.org, branch=self.branch_a, customer=self.customer,
            event_type=RiskEvent.EventType.OFF_HOURS_VERIFICATION, dedupe_key='t1', evidence={},
        )

    def test_staff_blocked_branch_scoped_admin_full(self):
        self.login_as(self.staff_user)
        self.assertEqual(self.client.get('/api/promotions/risk-events/').status_code, 403)

        RiskEvent.objects.create(
            organization=self.org, branch=self.branch_b,
            event_type=RiskEvent.EventType.STAFF_RAPID_VERIFICATIONS, dedupe_key='t2', evidence={},
        )
        self.login_as(self.branch_a_user)
        self.assertEqual(self.client.get('/api/promotions/risk-events/').data['count'], 1)
        self.login_as(self.admin)
        self.assertEqual(self.client.get('/api/promotions/risk-events/').data['count'], 2)

    def test_review_action(self):
        self.login_as(self.branch_a_user)
        resp = self.client.post(
            f'/api/promotions/risk-events/{self.event.id}/review/',
            {'status': 'dismissed', 'note': 'known regular'}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, RiskEvent.Status.DISMISSED)
        self.assertEqual(self.event.reviewed_by, self.branch_a_user)

    def test_cross_org_isolation(self):
        self.login_as(self.branch_b_user)
        bad = self.client.post(
            f'/api/promotions/risk-events/{self.event.id}/review/', {'status': 'dismissed'}, format='json',
        )
        self.assertIn(bad.status_code, (403, 404))


class StaffPermissionTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.campaign = make_campaign(self.branch_a)
        self.customer = register_customer(organization=self.org, phone='09011112222')

    def test_disabling_verify_blocks_that_staff_account(self):
        self.login_as(self.staff_user)
        ok = self.client.post('/api/promotions/spend-verifications/', {
            'card_token': self.customer.card_token, 'amount_yen': 2000,
        }, format='json')
        self.assertEqual(ok.status_code, 201)

        StaffPermission.objects.create(user=self.staff_user, can_verify_spend=False)
        blocked = self.client.post('/api/promotions/spend-verifications/', {
            'card_token': self.customer.card_token, 'amount_yen': 2000,
        }, format='json')
        self.assertEqual(blocked.status_code, 403)

    def test_admin_lists_and_toggles(self):
        self.login_as(self.admin)
        listing = self.client.get('/api/promotions/staff-permissions/')
        self.assertEqual(listing.status_code, 200)
        row = next(r for r in listing.data if r['account'] == self.staff_user.username)
        self.assertTrue(row['can_verify_spend'])  # default when no row

        toggled = self.client.patch(
            f'/api/promotions/staff-permissions/{self.staff_user.id}/',
            {'can_redeem_voucher': False, 'note': 'training'}, format='json',
        )
        self.assertEqual(toggled.status_code, 200)
        self.assertFalse(toggled.data['can_redeem_voucher'])

    def test_branch_account_cannot_manage_permissions(self):
        self.login_as(self.branch_a_user)
        self.assertEqual(self.client.get('/api/promotions/staff-permissions/').status_code, 403)


class RetentionTests(ApiTestCase):
    def test_stale_customer_is_erased_records_detached(self):
        campaign = make_campaign(self.branch_a)
        old = register_customer(organization=self.org, phone='09011112222', campaign=campaign)
        verify_spend(campaign=campaign, branch=self.branch_a, customer=old, amount_yen=3000,
                     verified_by=self.staff_user)
        fresh = register_customer(organization=self.org, phone='09099998888')

        Customer.objects.filter(pk=old.pk).update(
            last_seen_at=timezone.now() - timedelta(days=800),
            first_seen_at=timezone.now() - timedelta(days=800),
        )
        dry = purge_stale_customers(dry_run=True)
        self.assertEqual(dry['would_purge'], 1)

        result = purge_stale_customers()
        self.assertEqual(result['purged'], 1)
        self.assertFalse(Customer.objects.filter(pk=old.pk).exists())
        self.assertTrue(Customer.objects.filter(pk=fresh.pk).exists())
        sv = SpendVerification.objects.get()
        self.assertIsNone(sv.customer_id)
        self.assertTrue(sv.customer_deleted)


class CampaignReportTests(ApiTestCase):
    def test_report_shape(self):
        campaign = make_campaign(self.branch_a)
        only_prize(campaign, weight=1, reward_type=RewardType.DRINK)
        customer = register_customer(organization=self.org, phone='09011112222', campaign=campaign)
        verify_spend(campaign=campaign, branch=self.branch_a, customer=customer, amount_yen=12000,
                     verified_by=self.staff_user)
        redeem_points(customer=customer, campaign=campaign, kind='draw', request_id='r1')

        self.login_as(self.branch_a_user)
        month = timezone.localdate().strftime('%Y-%m')
        resp = self.client.get(f'/api/promotions/campaigns/{campaign.id}/report/?month={month}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['spend']['verifications'], 1)
        self.assertEqual(resp.data['spend']['total_amount'], 12000)
        self.assertEqual(resp.data['points']['earned'], 120)
        self.assertEqual(resp.data['points']['spent_on_draws'], 100)
        self.assertEqual(resp.data['draws']['total'], 1)
        self.assertGreaterEqual(resp.data['vouchers']['issued'], 1)
        self.assertEqual(len(resp.data['staff_stats']), 1)
