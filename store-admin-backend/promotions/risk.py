"""Rule-based risk flagging (打卡与抽奖实施方案.md §13).

A flag is a signal for a human to look at, never an automatic "fraud"
verdict and never a block — the hard rejections (future timestamp, same-day
double check-in, daily draw cap) live in `services` and raise there. These
rules only ever create `RiskEvent` rows.

Every entry point is wrapped in `_safe`: a bug in a rule must never break a
checkout, a draw, or a registration.
"""

import logging
from datetime import timedelta

from django.db import IntegrityError
from django.utils import timezone

from .models import (
    Customer, LotteryDraw, Prize, RiskEvent, SpendVerification, Voucher, VOUCHER_REWARD_TYPES,
)

logger = logging.getLogger(__name__)

# --- thresholds (kept here so they read as one tunable table) --------------
OFF_HOURS_START = 3   # local hour; confirming a paid checkout between
OFF_HOURS_END = 9     # 03:00 and 09:00 is unusual enough to note (hotels
                      # serving breakfast are the main false positive)
STAFF_RAPID_WINDOW = timedelta(minutes=10)
STAFF_RAPID_COUNT = 12
MULTI_BRANCH_WINDOW = timedelta(days=7)
MULTI_BRANCH_DISTINCT = 3
DEVICE_REGISTER_WINDOW = timedelta(hours=2)
DEVICE_REGISTER_COUNT = 3
RAPID_DRAW_WINDOW = timedelta(minutes=5)
RAPID_DRAW_COUNT = 4
HIGH_VALUE_STREAK_WINDOW = timedelta(days=30)
HIGH_VALUE_STREAK_COUNT = 3
HIGH_VALUE_FACE_YEN = 1000  # a cash voucher at/above this is "high value"


def _safe(fn):
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:  # pragma: no cover - defensive
            logger.exception('promotions.risk rule %s failed', fn.__name__)
            return []
    wrapper.__name__ = fn.__name__
    return wrapper


def _record(*, organization, event_type, dedupe_key, severity, evidence,
            branch=None, customer=None, staff_user=None, source_ref=''):
    try:
        RiskEvent.objects.get_or_create(
            dedupe_key=dedupe_key,
            defaults=dict(
                organization=organization, branch=branch, customer=customer,
                staff_user=staff_user, event_type=event_type, severity=severity,
                evidence=evidence, source_ref=source_ref,
            ),
        )
    except IntegrityError:  # pragma: no cover - concurrent identical flag
        pass


# ---------------------------------------------------------------------------
# Spend verification
# ---------------------------------------------------------------------------

@_safe
def evaluate_spend_verification(verification: SpendVerification):
    org = verification.branch.organization
    now = verification.verified_at or timezone.now()

    # off-hours confirmation
    local_hour = timezone.localtime(verification.consumed_at).hour
    if OFF_HOURS_START <= local_hour < OFF_HOURS_END:
        _record(
            organization=org, branch=verification.branch, customer=verification.customer,
            staff_user=verification.verified_by,
            event_type=RiskEvent.EventType.OFF_HOURS_VERIFICATION,
            dedupe_key=f'offhours:sv:{verification.pk}', severity=RiskEvent.Severity.LOW,
            source_ref=f'spendverification:{verification.pk}',
            evidence={'rule': 'off_hours', 'window': f'{OFF_HOURS_START}:00-{OFF_HOURS_END}:00',
                      'local_hour': local_hour},
        )

    # same staff, many confirmations, short window
    if verification.verified_by_id:
        recent = SpendVerification.objects.filter(
            verified_by_id=verification.verified_by_id,
            verified_at__gte=now - STAFF_RAPID_WINDOW,
        ).count()
        if recent >= STAFF_RAPID_COUNT:
            _record(
                organization=org, branch=verification.branch, staff_user=verification.verified_by,
                event_type=RiskEvent.EventType.STAFF_RAPID_VERIFICATIONS,
                dedupe_key=f'staffrapid:{verification.verified_by_id}:{now:%Y%m%d%H%M}',
                severity=RiskEvent.Severity.MEDIUM,
                source_ref=f'spendverification:{verification.pk}',
                evidence={'rule': 'staff_rapid', 'threshold': STAFF_RAPID_COUNT,
                          'observed': recent, 'window_minutes': STAFF_RAPID_WINDOW.seconds // 60},
            )

    # amount exactly equals an active voucher threshold for this campaign
    thresholds = set(
        Prize.objects.filter(
            campaign_id=verification.campaign_id, active=True, voucher_min_spend_yen__gt=0,
        ).values_list('voucher_min_spend_yen', flat=True)
    )
    if verification.amount_yen in thresholds:
        cust_hits = SpendVerification.objects.filter(
            customer_id=verification.customer_id, campaign_id=verification.campaign_id,
            amount_yen=verification.amount_yen, status=SpendVerification.Status.ACCEPTED,
        ).count() if verification.customer_id else 1
        _record(
            organization=org, branch=verification.branch, customer=verification.customer,
            staff_user=verification.verified_by,
            event_type=RiskEvent.EventType.AMOUNT_EQUALS_THRESHOLD,
            dedupe_key=f'threshold:sv:{verification.pk}',
            severity=RiskEvent.Severity.MEDIUM if cust_hits >= 3 else RiskEvent.Severity.LOW,
            source_ref=f'spendverification:{verification.pk}',
            evidence={'rule': 'amount_equals_threshold', 'amount_yen': verification.amount_yen,
                      'customer_repeat_count': cust_hits},
        )

    # same customer seen at many branches recently
    if verification.customer_id:
        branch_ids = set(
            SpendVerification.objects.filter(
                customer_id=verification.customer_id, verified_at__gte=now - MULTI_BRANCH_WINDOW,
            ).values_list('branch_id', flat=True)
        )
        if len(branch_ids) >= MULTI_BRANCH_DISTINCT:
            _record(
                organization=org, branch=verification.branch, customer=verification.customer,
                event_type=RiskEvent.EventType.CUSTOMER_MULTI_BRANCH,
                dedupe_key=f'multibranch:{verification.customer_id}:{now:%Y%W}',
                severity=RiskEvent.Severity.MEDIUM,
                source_ref=f'spendverification:{verification.pk}',
                evidence={'rule': 'customer_multi_branch', 'distinct_branches': len(branch_ids),
                          'window_days': MULTI_BRANCH_WINDOW.days},
            )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

@_safe
def evaluate_registration(customer: Customer, ip):
    if not ip:
        return
    now = timezone.now()
    same_ip = Customer.objects.filter(
        organization_id=customer.organization_id, registered_ip=ip,
        first_seen_at__gte=now - DEVICE_REGISTER_WINDOW,
    ).count()
    if same_ip >= DEVICE_REGISTER_COUNT:
        _record(
            organization=customer.organization,
            event_type=RiskEvent.EventType.DEVICE_MULTI_REGISTER,
            dedupe_key=f'device:{customer.organization_id}:{ip}:{now:%Y%m%d%H}',
            severity=RiskEvent.Severity.MEDIUM, customer=customer,
            source_ref=f'customer:{customer.pk}',
            evidence={'rule': 'device_multi_register', 'ip': ip, 'count': same_ip,
                      'window_hours': DEVICE_REGISTER_WINDOW.seconds // 3600},
        )


# ---------------------------------------------------------------------------
# Lottery draw
# ---------------------------------------------------------------------------

@_safe
def evaluate_draw(draw: LotteryDraw):
    if not draw.customer_id:
        return
    org = draw.campaign.branch.organization
    now = draw.drawn_at or timezone.now()

    rapid = LotteryDraw.objects.filter(
        customer_id=draw.customer_id, drawn_at__gte=now - RAPID_DRAW_WINDOW,
    ).count()
    if rapid >= RAPID_DRAW_COUNT:
        _record(
            organization=org, branch=draw.branch, customer=draw.customer,
            event_type=RiskEvent.EventType.CUSTOMER_RAPID_DRAWS,
            dedupe_key=f'rapiddraw:{draw.customer_id}:{now:%Y%m%d%H%M}',
            severity=RiskEvent.Severity.LOW,
            source_ref=f'draw:{draw.pk}',
            evidence={'rule': 'customer_rapid_draws', 'threshold': RAPID_DRAW_COUNT,
                      'observed': rapid, 'window_minutes': RAPID_DRAW_WINDOW.seconds // 60},
        )

    # concentrated high-value wins
    if draw.status == LotteryDraw.Status.WON and _is_high_value(draw):
        streak = 0
        for past in LotteryDraw.objects.filter(
            customer_id=draw.customer_id, status=LotteryDraw.Status.WON,
            drawn_at__gte=now - HIGH_VALUE_STREAK_WINDOW,
        ).select_related('prize'):
            if _is_high_value(past):
                streak += 1
        if streak >= HIGH_VALUE_STREAK_COUNT:
            _record(
                organization=org, branch=draw.branch, customer=draw.customer,
                event_type=RiskEvent.EventType.HIGH_VALUE_PRIZE_STREAK,
                dedupe_key=f'hvstreak:{draw.customer_id}:{now:%Y%m%d}',
                severity=RiskEvent.Severity.HIGH,
                source_ref=f'draw:{draw.pk}',
                evidence={'rule': 'high_value_prize_streak', 'count': streak,
                          'window_days': HIGH_VALUE_STREAK_WINDOW.days},
            )


def _is_high_value(draw: LotteryDraw) -> bool:
    rt = draw.reward_type_snapshot
    if rt not in VOUCHER_REWARD_TYPES:
        return False
    if rt == 'cash_voucher':
        prize = draw.prize
        face = int(prize.reward_config.get('face_yen', 0)) if prize else 0
        return face >= HIGH_VALUE_FACE_YEN
    return rt in ('chef_special',)


# ---------------------------------------------------------------------------
# PIN recovery
# ---------------------------------------------------------------------------

@_safe
def flag_pin_recovery_lockout(customer: Customer, *, ip=None, burst=0, day=0):
    """Called when phone+PIN recovery for a card hits the failure cap — a
    real owner rarely fumbles a PIN five times, so a lockout is worth a
    look (someone may be guessing at this customer's card)."""
    now = timezone.now()
    _record(
        organization=customer.organization, customer=customer,
        event_type=RiskEvent.EventType.PIN_RECOVERY_LOCKOUT,
        dedupe_key=f'pinlock:{customer.pk}:{now:%Y%m%d%H}',
        severity=RiskEvent.Severity.MEDIUM,
        source_ref=f'customer:{customer.pk}',
        evidence={'rule': 'pin_recovery_lockout', 'ip': ip or '',
                  'failures_1h': burst, 'failures_24h': day},
    )


# ---------------------------------------------------------------------------
# Void after value was already used
# ---------------------------------------------------------------------------

@_safe
def flag_void_after_redemption(verification: SpendVerification):
    """Called from `void_spend_verification`: if this spend fed points into
    a draw or voucher that has since been used, the manager needs to know —
    the value is already gone, only follow-up can recover it."""
    if not verification.customer_id:
        return
    org = verification.branch.organization
    used = Voucher.objects.filter(
        customer_id=verification.customer_id, status=Voucher.Status.REDEEMED,
        redeemed_at__gte=verification.verified_at,
    ).exists()
    drew = LotteryDraw.objects.filter(
        customer_id=verification.customer_id, drawn_at__gte=verification.verified_at,
    ).exists()
    if used or drew:
        _record(
            organization=org, branch=verification.branch, customer=verification.customer,
            staff_user=verification.voided_by,
            event_type=RiskEvent.EventType.VOIDED_AFTER_REDEMPTION,
            dedupe_key=f'voidafter:sv:{verification.pk}',
            severity=RiskEvent.Severity.HIGH,
            source_ref=f'spendverification:{verification.pk}',
            evidence={'rule': 'voided_after_redemption', 'voucher_redeemed': used, 'drew_after': drew,
                      'points_granted': verification.points_granted},
        )
