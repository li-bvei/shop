"""Transactional business logic for the promotions app.

Every function that moves a points balance follows the same shape as
inventory.services.adjust_stock: one atomic block, a row lock on the
Customer, the balance write and the matching PointsLedger row in the same
transaction so the ledger sum can never drift from the cached balance.
"""

import secrets
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.core import signing
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from . import risk
from .models import (
    Campaign, CheckInRecord, Customer, LotteryDraw, Milestone, MilestoneClaim, PointsLedger, Prize,
    RewardType, SpendVerification, Voucher,
)
from .utils import business_local_date, normalize_birthday_md, normalize_phone, normalize_pin

# redemption_code alphabet — no 0/O/1/I/L so a staff member can key it by
# hand off a customer's phone screen without ambiguity.
_CODE_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'

STORE_TOKEN_SALT = 'promotions.store_token'
GUEST_COOKIE_NAME = 'pc_guest'
GUEST_COOKIE_MAX_AGE = 34_560_000  # ~13 months

# A single confirmed spend is a table's bill, not a wedding banquet — a
# value past this is almost always a typo (an extra zero) and would grant a
# wildly wrong number of points. Staff are trusted and `void` exists, so
# this is a sanity rail, not a security control.
MAX_SPEND_YEN = 1_000_000


# ---------------------------------------------------------------------------
# Campaign availability
# ---------------------------------------------------------------------------

def campaign_is_open(campaign, now=None) -> bool:
    """Usable for registration / spend confirmation / points spend / draw:
    ACTIVE *and* within [starts_at, ends_at). Either bound null = open on
    that side. `status` alone is not enough — an ACTIVE campaign that has
    not started, or is past its end, must behave as closed everywhere."""
    if not campaign or campaign.status != Campaign.Status.ACTIVE:
        return False
    now = now or timezone.now()
    if campaign.starts_at and now < campaign.starts_at:
        return False
    if campaign.ends_at and now >= campaign.ends_at:
        return False
    return True


# ---------------------------------------------------------------------------
# Store QR token (printed sticker -> campaign + branch)
# ---------------------------------------------------------------------------

def make_store_token(campaign) -> str:
    return signing.dumps({'c': campaign.pk, 'b': campaign.branch_id}, salt=STORE_TOKEN_SALT)


def load_store_token(token: str) -> Campaign:
    """Resolve a printed store-QR token to its open campaign, or 400 with a
    deliberately vague message (a bad token must not reveal whether the
    campaign merely exists, or is just not running yet)."""
    try:
        data = signing.loads(token or '', salt=STORE_TOKEN_SALT)
    except signing.BadSignature:
        raise ValidationError({'store_token': ['store-token-invalid']})
    campaign = (
        Campaign.objects
        .select_related('branch', 'branch__organization')
        .filter(pk=data.get('c'))
        .first()
    )
    if not campaign_is_open(campaign):
        raise ValidationError({'store_token': ['store-token-invalid']})
    return campaign


# ---------------------------------------------------------------------------
# Customer registration / lookup
# ---------------------------------------------------------------------------

def _allocate_card_token() -> str:
    for _ in range(6):
        token = secrets.token_urlsafe(16)
        if not Customer.objects.filter(card_token=token).exists():
            return token
    raise RuntimeError('could not allocate a unique card_token')  # pragma: no cover


def register_customer(*, organization, phone, name='', birthday_md='', consent=True,
                      campaign=None, ip=None, pin='') -> Customer:
    """Issue the loyalty-card row for a NEW phone number. If the phone
    already has a card, this is a no-op beyond noting the visit — the
    returned object carries `was_created=False` and its `card_token` must
    NOT be handed back to the (unauthenticated) caller: phone numbers
    aren't secret, so returning the card credential for any phone would be
    a takeover vector (打卡与抽奖实施方案.md §14 — a stranger who knows
    your number should be able to see, never take). Recovery for a real
    owner on a new device is phone+PIN (full, if they set one),
    phone+birthday (read-only), or staff lookup in person. Profile fields —
    and the PIN — are only ever written on first registration, for the same
    reason."""
    phone = normalize_phone(phone)
    name = (name or '').strip()[:80]
    birthday_md = normalize_birthday_md(birthday_md)
    pin = normalize_pin(pin)
    now = timezone.now()

    with transaction.atomic():
        customer, created = Customer.objects.select_for_update().get_or_create(
            organization=organization,
            phone=phone,
            defaults={
                'card_token': _allocate_card_token(),
                'name': name,
                'birthday_md': birthday_md,
                'pin_hash': make_password(pin) if pin else '',
                'registered_campaign': campaign,
                'registered_ip': ip,
                'last_seen_at': now,
                'privacy_consented_at': now if consent else None,
            },
        )
        if not created:
            Customer.objects.filter(pk=customer.pk).update(last_seen_at=now)

    customer.was_created = created  # transient marker for the caller
    if created:
        risk.evaluate_registration(customer, ip)
    return customer


def set_customer_pin(customer, pin) -> None:
    """Set / replace the recovery PIN on a card the caller already holds
    (GuestSetPinView checks the guest token first)."""
    pin = normalize_pin(pin)
    if not pin:
        raise ValidationError({'pin': ['pin-required']})
    Customer.objects.filter(pk=customer.pk).update(pin_hash=make_password(pin))


# PIN recovery is deliberately the only self-service way back to a full
# (spendable) card, so it is the one place a 6-digit secret is brute-force
# exposed. Two overlapping caps: a short burst cap and a slow-grind daily
# cap, both counted per phone number in the shared cache.
PIN_FAIL_BURST_LIMIT = 5
PIN_FAIL_BURST_WINDOW = 3600      # 5 wrong tries in an hour -> 1h lock
PIN_FAIL_DAY_LIMIT = 15
PIN_FAIL_DAY_WINDOW = 86_400      # 15 wrong tries in a day -> 24h lock


_dummy_pin_hash = None


def _timing_equaliser_hash():
    """A throwaway hash to run check_password against when a phone has no
    PIN-enabled card, so a wrong-phone attempt costs the same ~time as a
    wrong-PIN one (no "does this number have a card" timing oracle). Built
    once, lazily — not at import (make_password is deliberately slow)."""
    global _dummy_pin_hash
    if _dummy_pin_hash is None:
        _dummy_pin_hash = make_password(secrets.token_hex(16))
    return _dummy_pin_hash


def _pin_fail_keys(phone):
    return f'promo:pinfail:burst:{phone}', f'promo:pinfail:day:{phone}'


def pin_recovery_locked(phone) -> bool:
    burst_key, day_key = _pin_fail_keys(phone)
    return (cache.get(burst_key, 0) >= PIN_FAIL_BURST_LIMIT
            or cache.get(day_key, 0) >= PIN_FAIL_DAY_LIMIT)


def _note_pin_failure(phone):
    burst_key, day_key = _pin_fail_keys(phone)
    burst = (cache.get(burst_key) or 0) + 1
    day = (cache.get(day_key) or 0) + 1
    cache.set(burst_key, burst, PIN_FAIL_BURST_WINDOW)
    cache.set(day_key, day, PIN_FAIL_DAY_WINDOW)
    return burst, day


def _clear_pin_failures(phone):
    burst_key, day_key = _pin_fail_keys(phone)
    cache.delete(burst_key)
    cache.delete(day_key)


def recover_card(*, phone, pin, ip=None) -> Customer:
    """Full-access recovery: phone + the 6-digit PIN set at registration.
    Returns the Customer (whose `card_token` the caller may then hand back
    and cookie) or raises ValidationError. Errors are deliberately generic
    — no oracle for "is this phone registered" or "does it have a PIN" —
    except the lockout, which a caller can only reach by trying."""
    phone = normalize_phone(phone)
    pin = normalize_pin(pin)
    if not pin:
        raise ValidationError({'pin': ['pin-required']})

    if pin_recovery_locked(phone):
        raise ValidationError({'detail': ['pin-recovery-locked']})

    candidates = list(
        Customer.objects.filter(phone=phone, status=Customer.Status.ACTIVE).exclude(pin_hash='')
    )
    verified = [c for c in candidates if check_password(pin, c.pin_hash)]
    if not candidates:
        check_password(pin, _timing_equaliser_hash())  # equalise timing
    # Exactly one card must match. Zero = wrong pin / no pin. More than one
    # = this phone + this PIN is registered at multiple chains — never
    # guess which card to hand back.
    customer = verified[0] if len(verified) == 1 else None

    if customer is None:
        burst, day = _note_pin_failure(phone)
        if burst >= PIN_FAIL_BURST_LIMIT or day >= PIN_FAIL_DAY_LIMIT:
            locked_target = candidates[0] if candidates else None
            if locked_target is not None:
                risk.flag_pin_recovery_lockout(locked_target, ip=ip, burst=burst, day=day)
        raise ValidationError({'detail': ['pin-recovery-failed']})

    _clear_pin_failures(phone)
    Customer.objects.filter(pk=customer.pk).update(last_seen_at=timezone.now())
    return customer


def touch_customer_seen(customer) -> None:
    Customer.objects.filter(pk=customer.pk).update(last_seen_at=timezone.now())


# ---------------------------------------------------------------------------
# Spend verification -> check-in + points
# ---------------------------------------------------------------------------

def verify_spend(*, campaign, branch, customer, amount_yen, table_number='',
                 consumed_at=None, verified_by=None, ip=None, request_id='') -> SpendVerification:
    """Record a staff-confirmed spend: log the visit (once per business
    day), grant points (¥1,000 -> campaign.points_per_1000yen), advance the
    stamp card if enabled. All in one transaction under a Customer row
    lock. `request_id` (optional) makes a retried / double-tapped request
    idempotent — every *real* spend still earns, but the same id twice
    returns the first result."""
    request_id = (request_id or '').strip()[:64]
    if campaign.branch_id != branch.id:
        raise ValidationError({'campaign': ['campaign-branch-mismatch']})
    if not campaign_is_open(campaign):
        raise ValidationError({'campaign': ['campaign-not-active']})
    if customer.organization_id != branch.organization_id:
        raise ValidationError({'customer': ['customer-outside-organization']})

    try:
        amount_yen = int(amount_yen)
    except (TypeError, ValueError):
        raise ValidationError({'amount_yen': ['amount-invalid']})
    if amount_yen < 0:
        raise ValidationError({'amount_yen': ['amount-negative']})
    if amount_yen > MAX_SPEND_YEN:
        raise ValidationError({'amount_yen': ['amount-too-large']})

    now = timezone.now()
    consumed_at = consumed_at or now
    if consumed_at > now + timedelta(minutes=5):
        raise ValidationError({'consumed_at': ['consumed-at-in-future']})
    # Guard against arbitrary backdating, but stay lenient enough for the
    # real cross-midnight case: a sale just before the 05:00 cutover that
    # the staff confirm a little after it. The check-in is filed against
    # the sale's own business day (business_local_date), not "now".
    if consumed_at < now - timedelta(hours=24):
        raise ValidationError({'consumed_at': ['consumed-at-too-old']})

    local_date = business_local_date(consumed_at, campaign.business_day_cutover)

    points = amount_yen // 1000 * campaign.points_per_1000yen
    qualifies_for_draw = bool(
        campaign.direct_draw_threshold_yen
        and amount_yen >= campaign.direct_draw_threshold_yen
    )
    direct_draws = campaign.max_draws_per_verification if qualifies_for_draw else 0

    with transaction.atomic():
        locked = Customer.objects.select_for_update().get(pk=customer.pk)
        if locked.status == Customer.Status.BLOCKED:
            raise ValidationError({'customer': ['customer-blocked']})

        if request_id:
            prior = SpendVerification.objects.filter(
                customer=locked, campaign=campaign, request_id=request_id,
            ).first()
            if prior:
                return prior

        check_in, ci_created = CheckInRecord.objects.get_or_create(
            customer=locked, campaign=campaign, local_date=local_date,
            defaults={'branch': branch, 'checked_in_at': now},
        )

        verification = SpendVerification.objects.create(
            customer=locked, check_in_record=check_in, campaign=campaign, branch=branch,
            table_number=(table_number or '').strip()[:16], amount_yen=amount_yen,
            consumed_at=consumed_at, points_granted=points, direct_draws_granted=direct_draws,
            verified_by=verified_by, source_ip=ip, request_id=request_id,
        )
        if ci_created:
            check_in.spend_verification = verification
            check_in.save(update_fields=['spend_verification'])

        update_fields = ['last_seen_at']
        locked.last_seen_at = now
        if points:
            locked.points_balance += points
            locked.lifetime_points_earned += points
            locked.last_activity_at = now
            update_fields += ['points_balance', 'lifetime_points_earned', 'last_activity_at']
        if direct_draws:
            locked.draw_chances += direct_draws
            update_fields.append('draw_chances')
        if campaign.stamp_target:
            locked.stamp_count += 1
            update_fields.append('stamp_count')
        locked.save(update_fields=update_fields)

        if points:
            PointsLedger.objects.create(
                customer=locked, delta=points, reason=PointsLedger.Reason.SPEND,
                source_ref=f'spendverification:{verification.pk}',
                balance_after=locked.points_balance,
            )
            _apply_milestones(customer=locked, campaign=campaign, now=now)

    verification.refresh_from_db()
    risk.evaluate_spend_verification(verification)
    return verification


# ---------------------------------------------------------------------------
# Manual points adjustment (admin) / void
# ---------------------------------------------------------------------------

def adjust_points(*, customer, delta, note, operator) -> PointsLedger:
    try:
        delta = int(delta)
    except (TypeError, ValueError):
        raise ValidationError({'delta': ['delta-invalid']})
    if delta == 0:
        raise ValidationError({'delta': ['delta-zero']})
    note = (note or '').strip()
    if not note:
        raise ValidationError({'note': ['note-required']})

    with transaction.atomic():
        locked = Customer.objects.select_for_update().get(pk=customer.pk)
        new_balance = locked.points_balance + delta
        if new_balance < 0:
            raise ValidationError({'delta': ['balance-would-go-negative']})
        locked.points_balance = new_balance
        locked.last_activity_at = timezone.now()
        locked.save(update_fields=['points_balance', 'last_activity_at'])
        entry = PointsLedger.objects.create(
            customer=locked, delta=delta, reason=PointsLedger.Reason.ADJUST,
            note=note[:255], operator=operator, balance_after=new_balance,
        )
    return entry


def void_spend_verification(*, verification, operator, reason) -> SpendVerification:
    """Reverse a spend confirmation: mark it voided and, if it granted
    points, write an offsetting ledger row and pull the balance back
    (floored at zero — the customer may already have spent the points; the
    ledger keeps the true trail either way)."""
    reason = (reason or '').strip()
    if not reason:
        raise ValidationError({'reason': ['reason-required']})
    if verification.status == SpendVerification.Status.VOIDED:
        raise ValidationError({'status': ['already-voided']})

    now = timezone.now()
    with transaction.atomic():
        locked_v = SpendVerification.objects.select_for_update().get(pk=verification.pk)
        if locked_v.status == SpendVerification.Status.VOIDED:
            raise ValidationError({'status': ['already-voided']})

        locked_v.status = SpendVerification.Status.VOIDED
        locked_v.voided_at = now
        locked_v.voided_by = operator
        locked_v.void_reason = reason[:255]
        locked_v.save(update_fields=['status', 'voided_at', 'voided_by', 'void_reason'])

        if locked_v.customer_id and (locked_v.points_granted or locked_v.direct_draws_granted):
            customer = Customer.objects.select_for_update().get(pk=locked_v.customer_id)
            fields = ['last_activity_at']
            customer.last_activity_at = now
            if locked_v.points_granted:
                customer.points_balance = max(0, customer.points_balance - locked_v.points_granted)
                customer.lifetime_points_earned = max(
                    0, customer.lifetime_points_earned - locked_v.points_granted,
                )
                fields += ['points_balance', 'lifetime_points_earned']
            if locked_v.direct_draws_granted:
                # Claw back only draw chances still unused; a draw already
                # taken stands (same rule as spent points).
                customer.draw_chances = max(0, customer.draw_chances - locked_v.direct_draws_granted)
                fields.append('draw_chances')
            customer.save(update_fields=fields)
            if locked_v.points_granted:
                PointsLedger.objects.create(
                    customer=customer, delta=-locked_v.points_granted, reason=PointsLedger.Reason.ADJUST,
                    source_ref=f'spendverification:{locked_v.pk}',
                    note=f'void: {reason[:200]}', operator=operator,
                    balance_after=customer.points_balance,
                )
    locked_v.refresh_from_db()
    risk.flag_void_after_redemption(locked_v)
    return locked_v


# ---------------------------------------------------------------------------
# APPI erasure
# ---------------------------------------------------------------------------

def _deidentify_and_delete(customer, *, void_reason) -> dict:
    """Detach + de-identify a customer's operational rows (kept for branch
    stats + staff audit), then remove the Customer row itself. Assumes it
    runs inside a transaction with `customer` row-locked."""
    checkins = CheckInRecord.objects.filter(customer=customer).update(
        customer=None, customer_deleted=True,
    )
    verifications = SpendVerification.objects.filter(customer=customer).update(
        customer=None, customer_deleted=True, table_number='',
    )
    ledger = PointsLedger.objects.filter(customer=customer).update(customer=None)
    LotteryDraw.objects.filter(customer=customer).update(customer=None, customer_deleted=True)
    vouchers_voided = Voucher.objects.filter(
        customer=customer, status=Voucher.Status.ACTIVE,
    ).update(status=Voucher.Status.VOID, void_reason=void_reason)
    Voucher.objects.filter(customer=customer).update(customer=None, customer_deleted=True)
    # RiskEvent.customer and MilestoneClaim CASCADE / SET_NULL with the row.
    customer_pk = customer.pk
    customer.delete()
    return {
        'customer_id': customer_pk,
        'checkins_detached': checkins,
        'verifications_detached': verifications,
        'ledger_detached': ledger,
        'vouchers_voided': vouchers_voided,
    }


def delete_customer_by_phone(*, organization, phone, operator=None) -> dict:
    """Respond to a "delete my data" request. See 打卡与抽奖实施方案.md
    §4.4 / promotions task doc §4.4."""
    phone = normalize_phone(phone)
    with transaction.atomic():
        try:
            customer = Customer.objects.select_for_update().get(organization=organization, phone=phone)
        except Customer.DoesNotExist:
            raise ValidationError({'phone': ['customer-not-found']})
        return _deidentify_and_delete(customer, void_reason='customer erased (APPI)')


def staff_can(user, action: str) -> bool:
    """`action` = 'verify_spend' | 'redeem_voucher'. An account with no
    StaffPermission row can do both (the phase-1 default); a manager adds a
    row to switch one off."""
    from .models import StaffPermission
    perm = StaffPermission.objects.filter(user_id=user.pk).first()
    return getattr(perm, f'can_{action}') if perm else True


# ---------------------------------------------------------------------------
# Phase 2 / 2.5 — vouchers, milestones, lottery, points spending, expiry
# ---------------------------------------------------------------------------

def _allocate_redemption_code() -> str:
    rng = secrets.SystemRandom()
    for _ in range(8):
        code = ''.join(rng.choice(_CODE_ALPHABET) for _ in range(8))
        if not Voucher.objects.filter(redemption_code=code).exists():
            return code
    raise RuntimeError('could not allocate a unique redemption_code')  # pragma: no cover


def _voucher_label(reward_type, config) -> str:
    if config.get('label'):
        return config['label']
    if reward_type == RewardType.CASH_VOUCHER:
        return f'¥{int(config.get("face_yen", 0)):,} 割引券'
    if reward_type == RewardType.CHEF_SPECIAL:
        cap = int(config.get('menu_value_cap_yen', 0))
        return f'本日の主厨指定料理（メニュー価格 ¥{cap:,} まで）' if cap else '本日の主厨指定料理'
    return dict(RewardType.choices).get(reward_type, reward_type)


def _issue_voucher(*, customer, campaign, branch, reward_type, config, expires_days,
                   source, min_spend=0, requires_approval=False, source_draw=None,
                   source_milestone=None, redeem_request_id='') -> Voucher:
    """Build the frozen snapshot + code for one next-visit voucher. Assumes
    it runs inside a transaction with `customer` already row-locked."""
    config = dict(config or {})
    snapshot = {**config, 'label': _voucher_label(reward_type, config)}
    face_min = int(config.get('min_spend_yen', 0)) if reward_type == RewardType.CASH_VOUCHER else 0
    return Voucher.objects.create(
        customer=customer, campaign=campaign, branch=branch, source=source,
        source_draw=source_draw, source_milestone=source_milestone,
        reward_type=reward_type, config_snapshot=snapshot,
        min_spend_yen=max(min_spend or 0, face_min),
        requires_manual_approval=requires_approval,
        redemption_code=_allocate_redemption_code(),
        redeem_request_id=redeem_request_id,
        expires_at=timezone.now() + timedelta(days=expires_days or 30),
    )


def _apply_milestones(*, customer, campaign, now) -> list:
    """Issue a voucher for every campaign milestone the customer's
    lifetime_points_earned now covers and hasn't claimed. Must be called
    with `customer` row-locked (it is, inside verify_spend)."""
    claimed = set(
        MilestoneClaim.objects.filter(customer=customer).values_list('milestone_id', flat=True)
    )
    due = (
        Milestone.objects
        .filter(campaign=campaign, active=True, points_threshold__lte=customer.lifetime_points_earned)
        .exclude(id__in=claimed)
        .order_by('points_threshold')
    )
    issued = []
    for milestone in due:
        voucher = _issue_voucher(
            customer=customer, campaign=campaign, branch=None,
            reward_type=milestone.reward_type, config=milestone.reward_config,
            expires_days=milestone.voucher_expires_after_days,
            source=Voucher.Source.MILESTONE, source_milestone=milestone,
        )
        MilestoneClaim.objects.create(
            customer=customer, milestone=milestone, voucher=voucher,
            lifetime_points_at_claim=customer.lifetime_points_earned,
        )
        issued.append(voucher)
    return issued


def _pick_prize(campaign, branch, local_date):
    """Row-lock the pool, filter to what's actually drawable right now
    (active, weight>0, lifetime stock left, under today's per-branch cap),
    and pick one weighted by a cryptographic RNG. Returns
    (prize, total_weight)."""
    prizes = list(
        Prize.objects.select_for_update()
        .filter(campaign=campaign, active=True, weight__gt=0)
        .order_by('display_order', 'id')
    )
    available = []
    for prize in prizes:
        if prize.remaining_stock is not None and prize.remaining_stock <= 0:
            continue
        if prize.daily_stock is not None:
            won_today = LotteryDraw.objects.filter(
                prize=prize, branch=branch, local_date=local_date, status=LotteryDraw.Status.WON,
            ).count()
            if won_today >= prize.daily_stock:
                continue
        available.append(prize)

    if not available:
        raise ValidationError({'prize': ['no-prizes-available']})

    total_weight = sum(p.weight for p in available)
    roll = secrets.SystemRandom().randint(1, total_weight)
    cumulative = 0
    for prize in available:
        cumulative += prize.weight
        if roll <= cumulative:
            return prize, total_weight
    return available[-1], total_weight  # pragma: no cover (float-free, can't fall through)


def draw_lottery(*, campaign, branch, customer, source, request_id,
                 spend_verification=None) -> LotteryDraw:
    """Run one weighted draw. Idempotent on `request_id`. For source
    'points' it spends campaign.points_per_draw; for 'direct' it spends one
    Customer.draw_chances. A points_refund prize hands points back; every
    other prize issues a next-visit Voucher."""
    request_id = (request_id or '').strip()
    if not request_id:
        raise ValidationError({'request_id': ['request-id-required']})

    # Idempotency is per-customer: a replay only ever hands back *this*
    # customer's own earlier draw. request_id is globally unique at the DB
    # level, so a guest replaying someone else's id must not be shown that
    # draw's prize / voucher code — it falls through to the INSERT and the
    # IntegrityError branch below turns it into a plain 400.
    existing = (
        LotteryDraw.objects
        .filter(request_id=request_id, customer=customer)
        .select_related('prize')
        .first()
    )
    if existing:
        return existing

    if not campaign_is_open(campaign):
        raise ValidationError({'campaign': ['campaign-not-active']})

    now = timezone.now()
    local_date = business_local_date(now, campaign.business_day_cutover)

    try:
        with transaction.atomic():
            locked = Customer.objects.select_for_update().get(pk=customer.pk)
            if locked.status == Customer.Status.BLOCKED:
                raise ValidationError({'customer': ['customer-blocked']})

            cap = campaign.max_draws_per_customer_per_day
            if cap is not None:  # None = no cap; 0 = block all draws
                todays = LotteryDraw.objects.filter(
                    customer=locked, campaign=campaign, local_date=local_date,
                ).count()
                if todays >= cap:
                    raise ValidationError({'draw': ['daily-draw-limit-reached']})

            points_spent = 0
            if source == LotteryDraw.Source.POINTS:
                points_spent = campaign.points_per_draw
                if locked.points_balance < points_spent:
                    raise ValidationError({'points': ['insufficient-points']})
            elif source == LotteryDraw.Source.DIRECT:
                if locked.draw_chances < 1:
                    raise ValidationError({'draw': ['no-draw-chances']})
            else:
                raise ValidationError({'source': ['invalid-source']})

            prize, total_weight = _pick_prize(campaign, branch, local_date)

            is_refund = prize.reward_type == RewardType.POINTS_REFUND
            refund = int(prize.reward_config.get('points', 0)) if is_refund else 0
            status = LotteryDraw.Status.REFUND if is_refund else LotteryDraw.Status.WON

            if not is_refund and prize.remaining_stock is not None:
                prize.remaining_stock -= 1
                prize.save(update_fields=['remaining_stock'])

            draw = LotteryDraw.objects.create(
                campaign=campaign, branch=branch, customer=locked, source=source,
                points_spent=points_spent, spend_verification=spend_verification,
                request_id=request_id, prize=prize, prize_name_snapshot=prize.name,
                reward_type_snapshot=prize.reward_type, weight_snapshot=prize.weight,
                total_weight_snapshot=total_weight, status=status, local_date=local_date,
                points_refunded=refund,
            )

            fields = []
            if source == LotteryDraw.Source.POINTS:
                locked.points_balance -= points_spent
                fields.append('points_balance')
            elif source == LotteryDraw.Source.DIRECT:
                locked.draw_chances -= 1
                fields.append('draw_chances')
            if refund:
                locked.points_balance += refund
                if 'points_balance' not in fields:
                    fields.append('points_balance')
            if fields:
                locked.last_activity_at = now
                fields.append('last_activity_at')
                locked.save(update_fields=fields)

            if points_spent:
                PointsLedger.objects.create(
                    customer=locked, delta=-points_spent, reason=PointsLedger.Reason.DRAW,
                    source_ref=f'draw:{draw.pk}', balance_after=locked.points_balance,
                )
            if refund:
                PointsLedger.objects.create(
                    customer=locked, delta=refund, reason=PointsLedger.Reason.DRAW_REFUND,
                    source_ref=f'draw:{draw.pk}', balance_after=locked.points_balance,
                )

            if prize.produces_voucher:
                _issue_voucher(
                    customer=locked, campaign=campaign, branch=branch,
                    reward_type=prize.reward_type, config=prize.reward_config,
                    expires_days=prize.voucher_expires_after_days,
                    min_spend=prize.voucher_min_spend_yen,
                    requires_approval=prize.requires_manual_approval,
                    source=Voucher.Source.LOTTERY, source_draw=draw,
                )
    except IntegrityError:
        # Lost the request_id race with this same customer's concurrent
        # request — hand back that draw. A collision with a *different*
        # customer's id is not a safe replay: surface it as a 400.
        won = (
            LotteryDraw.objects
            .filter(request_id=request_id, customer=customer)
            .select_related('prize')
            .first()
        )
        if won:
            return won
        raise ValidationError({'request_id': ['request-id-already-used']})

    draw.refresh_from_db()
    risk.evaluate_draw(draw)
    return draw


def redeem_points(*, customer, campaign, kind, request_id, branch=None) -> dict:
    """Spend points on a draw (kind='draw') or a fixed-value voucher
    (kind='voucher'). Idempotent per (customer, request_id)."""
    request_id = (request_id or '').strip()
    if not request_id:
        raise ValidationError({'request_id': ['request-id-required']})
    if not campaign_is_open(campaign):
        raise ValidationError({'campaign': ['campaign-not-active']})

    if kind == 'draw':
        draw = draw_lottery(
            campaign=campaign, branch=branch, customer=customer,
            source=LotteryDraw.Source.POINTS, request_id=request_id,
        )
        return {'kind': 'draw', 'draw': draw}

    if kind != 'voucher':
        raise ValidationError({'kind': ['kind-must-be-draw-or-voucher']})

    cost = campaign.points_per_voucher
    face = campaign.voucher_yen_per_unit
    with transaction.atomic():
        locked = Customer.objects.select_for_update().get(pk=customer.pk)
        if locked.status == Customer.Status.BLOCKED:
            raise ValidationError({'customer': ['customer-blocked']})

        already = Voucher.objects.filter(
            customer=locked, source=Voucher.Source.POINTS_REDEEM, redeem_request_id=request_id,
        ).first()
        if already:
            return {'kind': 'voucher', 'voucher': already}

        if locked.points_balance < cost:
            raise ValidationError({'points': ['insufficient-points']})

        locked.points_balance -= cost
        locked.last_activity_at = timezone.now()
        locked.save(update_fields=['points_balance', 'last_activity_at'])

        voucher = _issue_voucher(
            customer=locked, campaign=campaign, branch=branch,
            reward_type=RewardType.CASH_VOUCHER, config={'face_yen': face},
            expires_days=45, source=Voucher.Source.POINTS_REDEEM,
            redeem_request_id=request_id,
        )
        PointsLedger.objects.create(
            customer=locked, delta=-cost, reason=PointsLedger.Reason.VOUCHER,
            source_ref=f'voucher:{voucher.pk}', balance_after=locked.points_balance,
        )
    return {'kind': 'voucher', 'voucher': voucher}


def redeem_voucher(*, voucher, branch, operator, spend_amount_yen=None, approved_by=None) -> Voucher:
    """Staff marks a voucher used at checkout. Validates ownership scope,
    status, expiry, min-spend and (top prizes) manager approval. Single
    use."""
    now = timezone.now()
    fresh = Voucher.objects.select_related('campaign', 'campaign__branch').get(pk=voucher.pk)

    if fresh.campaign.branch.organization_id != branch.organization_id:
        raise ValidationError({'voucher': ['voucher-outside-organization']})
    if fresh.status == Voucher.Status.VOID:
        raise ValidationError({'voucher': ['voucher-void']})
    if fresh.status == Voucher.Status.EXPIRED or fresh.expires_at <= now:
        # Persist the lapse outside any transaction we might roll back.
        Voucher.objects.filter(pk=fresh.pk, status=Voucher.Status.ACTIVE).update(
            status=Voucher.Status.EXPIRED,
        )
        raise ValidationError({'voucher': ['voucher-expired']})

    spend_value = None
    if fresh.min_spend_yen:
        try:
            spend_value = int(spend_amount_yen)
        except (TypeError, ValueError):
            raise ValidationError({'spend_amount_yen': ['min-spend-required']})
        if spend_value < fresh.min_spend_yen:
            raise ValidationError({'spend_amount_yen': ['min-spend-not-met']})
    elif spend_amount_yen not in (None, ''):
        try:
            spend_value = int(spend_amount_yen)
        except (TypeError, ValueError):
            spend_value = None

    if fresh.requires_manual_approval and not approved_by:
        raise ValidationError({'voucher': ['manager-approval-required']})

    with transaction.atomic():
        v = Voucher.objects.select_for_update().get(pk=voucher.pk)
        if v.status == Voucher.Status.REDEEMED:
            raise ValidationError({'voucher': ['voucher-already-redeemed']})
        if v.status != Voucher.Status.ACTIVE:
            raise ValidationError({'voucher': ['voucher-not-active']})
        v.status = Voucher.Status.REDEEMED
        v.redeemed_at = now
        v.redeemed_by = operator
        v.redeemed_branch = branch
        v.redeemed_spend_yen = spend_value
        v.approved_by = approved_by
        v.save(update_fields=[
            'status', 'redeemed_at', 'redeemed_by', 'redeemed_branch', 'redeemed_spend_yen', 'approved_by',
        ])
    return v


# Low-value next-visit items a customer can have confirmed by tapping on
# their own phone (staff standing there, item costs the store ~nothing).
# Cash vouchers and the chef's special still go through the staff kiosk.
SELF_SERVE_REWARD_TYPES = frozenset({
    RewardType.DRINK, RewardType.DESSERT, RewardType.SIDE_DISH,
})


def guest_redeem_voucher(*, customer, redemption_code) -> Voucher:
    """The customer slides 'staff confirm' on their own phone for a
    drink / dessert / side-dish voucher — no code entry, no staff login.
    `redeemed_by` stays null, which is how the staff list shows it was a
    self-serve confirmation."""
    code = (redemption_code or '').strip().upper()
    now = timezone.now()
    with transaction.atomic():
        v = (
            Voucher.objects.select_for_update()
            .select_related('campaign', 'campaign__branch')
            .filter(redemption_code=code, customer=customer)
            .first()
        )
        if not v:
            raise ValidationError({'voucher': ['voucher-not-found']})
        if v.reward_type not in SELF_SERVE_REWARD_TYPES or v.requires_manual_approval:
            raise ValidationError({'voucher': ['voucher-needs-staff']})
        if v.status == Voucher.Status.REDEEMED:
            raise ValidationError({'voucher': ['voucher-already-redeemed']})
        if v.status != Voucher.Status.ACTIVE or v.expires_at <= now:
            if v.status == Voucher.Status.ACTIVE:
                Voucher.objects.filter(pk=v.pk, status=Voucher.Status.ACTIVE).update(
                    status=Voucher.Status.EXPIRED,
                )
            raise ValidationError({'voucher': ['voucher-not-redeemable']})
        v.status = Voucher.Status.REDEEMED
        v.redeemed_at = now
        v.redeemed_branch = v.campaign.branch
        v.save(update_fields=['status', 'redeemed_at', 'redeemed_branch'])
    return v


def expire_stale_points(*, now=None) -> dict:
    """Housekeeping: zero the balance of any customer with no points
    activity for their campaign's `points_expire_months` (default 12), and
    log it in the ledger. Intended to run daily from a management command /
    cron."""
    now = now or timezone.now()
    result = {'customers': 0, 'points': 0}

    candidates = (
        Customer.objects
        .filter(points_balance__gt=0, last_activity_at__isnull=False)
        .select_related('registered_campaign')
        .iterator()
    )
    for customer in candidates:
        months = (
            customer.registered_campaign.points_expire_months
            if customer.registered_campaign else 12
        )
        cutoff = now - timedelta(days=months * 30)
        if customer.last_activity_at and customer.last_activity_at > cutoff:
            continue
        with transaction.atomic():
            locked = Customer.objects.select_for_update().get(pk=customer.pk)
            if locked.points_balance <= 0 or (locked.last_activity_at and locked.last_activity_at > cutoff):
                continue
            expired = locked.points_balance
            locked.points_balance = 0
            locked.last_activity_at = now
            locked.save(update_fields=['points_balance', 'last_activity_at'])
            PointsLedger.objects.create(
                customer=locked, delta=-expired, reason=PointsLedger.Reason.EXPIRE,
                balance_after=0, note=f'expired after ~{months}mo inactivity',
            )
        result['customers'] += 1
        result['points'] += expired
    return result
