from datetime import time

from django.conf import settings
from django.db import models


class Campaign(models.Model):
    """One branch's running loyalty programme — the config the check-in /
    spend-verification / points flow reads from. A branch normally has one
    `active` campaign at a time; older ones stay as `ended` for their
    history. Organization is traced through `branch` (same as every other
    branch-owned model here), never stored twice."""

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        ACTIVE = 'active', 'Active'
        PAUSED = 'paused', 'Paused'
        ENDED = 'ended', 'Ended'

    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.CASCADE, related_name='promo_campaigns',
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)

    # Points economy (phase 0 starting values — calibrated with real data
    # later, see 打卡与抽奖实施方案.md §5). `points_per_draw` /
    # `points_per_voucher` / `voucher_yen_per_unit` are stored now but only
    # consumed from phase 2.5 onward.
    points_per_1000yen = models.PositiveIntegerField(default=10)
    points_per_draw = models.PositiveIntegerField(default=100)
    points_per_voucher = models.PositiveIntegerField(default=100)
    voucher_yen_per_unit = models.PositiveIntegerField(default=100)
    points_expire_months = models.PositiveIntegerField(default=12)

    # null = the optional "spend over ¥X grants a free draw" dual track is
    # off (phase 2.5).
    direct_draw_threshold_yen = models.PositiveIntegerField(null=True, blank=True)
    max_draws_per_verification = models.PositiveIntegerField(default=1)
    # null = no per-customer daily draw cap.
    max_draws_per_customer_per_day = models.PositiveIntegerField(default=10, null=True, blank=True)

    # null = the visit-count stamp card is off; otherwise the number of
    # confirmed visits that completes one stamp card.
    stamp_target = models.PositiveIntegerField(null=True, blank=True)

    # A sale at 02:00 belongs to the previous business day for a store that
    # trades past midnight. See promotions.utils.business_local_date.
    business_day_cutover = models.TimeField(default=time(5, 0))

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.branch_id} / {self.name}'


class Customer(models.Model):
    """A store loyalty-card holder, keyed by phone number within one
    Organization. The phone is collected openly and never verified — a fake
    or borrowed number is accepted by design (打卡与抽奖实施方案.md §3); all
    real value is gated on a staff spend-verification, not on the number.
    `points_balance` / `stamp_count` are summaries maintained only by
    promotions.services under a row lock, never written from a serializer."""

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        BLOCKED = 'blocked', 'Blocked'

    organization = models.ForeignKey(
        'organizations.Organization', on_delete=models.PROTECT, related_name='promo_customers',
    )
    # The campaign the customer signed up under — the one whose rate / stamp
    # target the card page shows. Points and stamps themselves are
    # Organization-wide, not tied to this campaign.
    registered_campaign = models.ForeignKey(
        'promotions.Campaign', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    phone = models.CharField(max_length=20)
    name = models.CharField(max_length=80, blank=True)
    # Month/day only, stored as 'MM-DD'. Used for birthday vouchers (phase 4)
    # and as the weak second factor for read-only login.
    birthday_md = models.CharField(max_length=5, blank=True)
    # Opaque, unguessable, non-rotating — this is what the card QR carries
    # and what the counter scanner reads. secrets.token_urlsafe(16).
    card_token = models.CharField(max_length=64, unique=True)
    # Optional 6-digit recovery PIN (Django password hash, never plaintext).
    # Empty = not set. This is the security boundary for regaining *full*
    # (spend) access on a new device — phone + PIN, rate-limited, no
    # self-service reset. The phone+birthday path stays read-only.
    pin_hash = models.CharField(max_length=128, blank=True, default='')

    points_balance = models.IntegerField(default=0)
    # Monotonic total of points ever earned from spending — drives the
    # cumulative-points milestones (never decremented by spending or expiry).
    lifetime_points_earned = models.PositiveIntegerField(default=0)
    stamp_count = models.PositiveIntegerField(default=0)
    # Free lottery draws granted by the "spend over ¥X" dual track, not yet
    # used. Points-funded draws are spent-and-drawn in one request instead.
    draw_chances = models.PositiveIntegerField(default=0)

    # Best-effort source IP of the first registration — a weak "device"
    # proxy for the "one device, many phones" risk rule (there is no
    # device fingerprint, by design).
    registered_ip = models.GenericIPAddressField(null=True, blank=True)

    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    # Last time points were earned/spent — the clock the 12-month expiry
    # runs off (phase 2.5).
    last_activity_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    risk_level = models.CharField(max_length=16, default='normal')
    privacy_consented_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-last_seen_at', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'phone'], name='unique_promo_customer_phone_per_org',
            ),
        ]
        indexes = [
            models.Index(fields=['organization', 'phone']),
            models.Index(fields=['organization', 'name']),
        ]

    def __str__(self):
        return f'{self.name or self.phone}'

    @property
    def phone_masked(self):
        """Last four digits only — what staff-facing responses show."""
        digits = ''.join(ch for ch in self.phone if ch.isdigit())
        return f'••••{digits[-4:]}' if digits else ''


class PointsLedger(models.Model):
    """Immutable points ledger — every earn / spend / expiry / manual
    adjustment is exactly one row, and `Customer.points_balance` is their
    running sum. Never updated or deleted; a correction is a new offsetting
    row (same rule as inventory.StockTransaction). `customer` goes null,
    not away, when a customer is erased for an APPI request — the financial
    trail is kept."""

    class Reason(models.TextChoices):
        SPEND = 'spend', 'Spend'
        MILESTONE = 'milestone', 'Milestone'
        DRAW = 'draw', 'Lottery draw'          # points spent on a draw
        DRAW_REFUND = 'draw_refund', 'Draw refund'  # "thanks for playing" points back
        VOUCHER = 'voucher', 'Voucher redeem'  # points spent on a voucher
        EXPIRE = 'expire', 'Expiry'
        ADJUST = 'adjust', 'Manual adjustment'

    customer = models.ForeignKey(
        Customer, on_delete=models.SET_NULL, null=True, related_name='points_ledger',
    )
    delta = models.IntegerField(help_text='Positive = earned, negative = spent/expired.')
    reason = models.CharField(max_length=16, choices=Reason.choices)
    # Lightweight provenance pointer, e.g. 'spendverification:42'. Kept as a
    # plain string rather than a GenericForeignKey — it's only ever read by
    # a human tracing "why did my balance change".
    source_ref = models.CharField(max_length=64, blank=True)
    balance_after = models.IntegerField()
    note = models.CharField(max_length=255, blank=True)
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.customer_id}: {self.delta:+d} ({self.reason})'


class CheckInRecord(models.Model):
    """One visit, one business day. Produced by a SpendVerification (the
    only trusted event). The unique constraint is what dedupes a second
    confirmation on the same business day — phase 1 still accepts that
    second spend, it just doesn't log a second check-in."""

    customer = models.ForeignKey(
        Customer, on_delete=models.SET_NULL, null=True, related_name='checkins',
    )
    customer_deleted = models.BooleanField(default=False)
    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.CASCADE, related_name='promo_checkins',
    )
    campaign = models.ForeignKey(Campaign, on_delete=models.PROTECT, related_name='checkins')
    spend_verification = models.ForeignKey(
        'promotions.SpendVerification', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    checked_in_at = models.DateTimeField()
    local_date = models.DateField(help_text='Business day, per Campaign.business_day_cutover.')
    result = models.CharField(max_length=16, default='ok')
    risk_level = models.CharField(max_length=16, default='normal')

    class Meta:
        ordering = ['-checked_in_at', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['customer', 'campaign', 'local_date'], name='unique_promo_checkin_per_day',
            ),
        ]

    def __str__(self):
        return f'{self.customer_id} @ {self.branch_id} {self.local_date}'


class SpendVerification(models.Model):
    """The single trusted event in the whole feature: a signed-in staff
    member confirmed, with the customer present at checkout, that this
    amount was spent. Points are granted from here and nowhere else.
    Append-only — a normal PATCH/DELETE is refused; corrections go through
    the `void` action, which reverses the points in the ledger."""

    class Status(models.TextChoices):
        ACCEPTED = 'accepted', 'Accepted'
        VOIDED = 'voided', 'Voided'

    customer = models.ForeignKey(
        Customer, on_delete=models.SET_NULL, null=True, related_name='spend_verifications',
    )
    customer_deleted = models.BooleanField(default=False)
    check_in_record = models.ForeignKey(
        CheckInRecord, on_delete=models.SET_NULL, null=True, blank=True, related_name='spend_verifications',
    )
    campaign = models.ForeignKey(Campaign, on_delete=models.PROTECT, related_name='spend_verifications')
    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.CASCADE, related_name='promo_spend_verifications',
    )
    table_number = models.CharField(max_length=16, blank=True)
    amount_yen = models.PositiveIntegerField()
    consumed_at = models.DateTimeField()
    points_granted = models.IntegerField(default=0)
    direct_draws_granted = models.PositiveIntegerField(default=0)  # phase 2.5 dual track

    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+',
    )
    verified_at = models.DateTimeField(auto_now_add=True)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACCEPTED)
    risk_level = models.CharField(max_length=16, default='normal')

    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    void_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.customer_id} ¥{self.amount_yen} ({self.status})'


# ---------------------------------------------------------------------------
# Phase 2 / 2.5 — lottery, prize pool, vouchers, milestones
# ---------------------------------------------------------------------------

class RewardType(models.TextChoices):
    CASH_VOUCHER = 'cash_voucher', 'Cash voucher'
    DRINK = 'drink', 'Drink'
    DESSERT = 'dessert', 'Dessert'
    SIDE_DISH = 'side_dish', 'Side dish'
    CHEF_SPECIAL = 'chef_special', "Chef's special"
    POINTS_REFUND = 'points_refund', 'Points refund'


# reward_type -> does winning it produce a next-visit Voucher?
VOUCHER_REWARD_TYPES = {
    RewardType.CASH_VOUCHER, RewardType.DRINK, RewardType.DESSERT,
    RewardType.SIDE_DISH, RewardType.CHEF_SPECIAL,
}


class Prize(models.Model):
    """One row of the weighted prize pool for a campaign. Probability is
    weight / sum(active weights), computed live at draw time; the drawn
    weight is snapshotted onto LotteryDraw so later tuning never rewrites
    history. `reward_config` shape depends on `reward_type` — see
    promotions.serializers.validate_reward_config and 开发任务书 §4.8."""

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='prizes')
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True)
    display_order = models.PositiveIntegerField(default=0)

    weight = models.PositiveIntegerField(help_text='Relative odds; 0 disables without deleting.')
    reward_type = models.CharField(max_length=16, choices=RewardType.choices)
    reward_config = models.JSONField(default=dict, blank=True)

    # null = unlimited. total_stock is the lifetime cap; daily_stock is the
    # per-branch-per-business-day cap (the ¥5,000 voucher is 1/day/branch).
    total_stock = models.PositiveIntegerField(null=True, blank=True)
    remaining_stock = models.PositiveIntegerField(null=True, blank=True)
    daily_stock = models.PositiveIntegerField(null=True, blank=True)

    voucher_expires_after_days = models.PositiveIntegerField(default=30)
    voucher_min_spend_yen = models.PositiveIntegerField(default=0)
    requires_manual_approval = models.BooleanField(default=False)

    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['campaign', 'display_order', 'id']

    def __str__(self):
        return f'{self.name} (w{self.weight})'

    @property
    def produces_voucher(self):
        return self.reward_type in VOUCHER_REWARD_TYPES


class Milestone(models.Model):
    """A cumulative-points threshold that hands out a bonus voucher the
    first time a customer's lifetime_points_earned crosses it (300 / 800 /
    2500 -> drink / dessert / ¥500 voucher by default)."""

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='milestones')
    points_threshold = models.PositiveIntegerField()
    reward_type = models.CharField(max_length=16, choices=RewardType.choices)
    reward_config = models.JSONField(default=dict, blank=True)
    voucher_expires_after_days = models.PositiveIntegerField(default=45)
    display_label = models.CharField(max_length=120, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['campaign', 'points_threshold']
        constraints = [
            models.UniqueConstraint(
                fields=['campaign', 'points_threshold'], name='unique_promo_milestone_threshold',
            ),
        ]

    def __str__(self):
        return f'{self.campaign_id} @ {self.points_threshold}pts'


class LotteryDraw(models.Model):
    """One draw. Immutable once created. `request_id` is unique so a
    double-tapped "draw" button never draws twice."""

    class Source(models.TextChoices):
        POINTS = 'points', 'Points redemption'
        DIRECT = 'direct', 'Spend threshold'

    class Status(models.TextChoices):
        WON = 'won', 'Won a prize'
        REFUND = 'refund', 'Points refund only'

    campaign = models.ForeignKey(Campaign, on_delete=models.PROTECT, related_name='draws')
    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.SET_NULL, null=True, related_name='promo_draws',
    )
    customer = models.ForeignKey(
        Customer, on_delete=models.SET_NULL, null=True, related_name='draws',
    )
    customer_deleted = models.BooleanField(default=False)
    source = models.CharField(max_length=10, choices=Source.choices)
    points_spent = models.PositiveIntegerField(default=0)
    spend_verification = models.ForeignKey(
        SpendVerification, on_delete=models.SET_NULL, null=True, blank=True, related_name='draws',
    )
    request_id = models.CharField(max_length=64, unique=True)

    prize = models.ForeignKey(Prize, on_delete=models.SET_NULL, null=True, blank=True, related_name='draws')
    prize_name_snapshot = models.CharField(max_length=120, blank=True)
    reward_type_snapshot = models.CharField(max_length=16, blank=True)
    weight_snapshot = models.PositiveIntegerField(default=0)
    total_weight_snapshot = models.PositiveIntegerField(default=0)
    points_refunded = models.PositiveIntegerField(default=0)

    status = models.CharField(max_length=10, choices=Status.choices)
    drawn_at = models.DateTimeField(auto_now_add=True)
    local_date = models.DateField(help_text='Business day of the draw, for daily-stock counting.')

    class Meta:
        ordering = ['-drawn_at', '-id']
        indexes = [
            models.Index(fields=['prize', 'branch', 'local_date']),
            models.Index(fields=['customer', 'local_date']),
        ]

    def __str__(self):
        return f'{self.customer_id}: {self.prize_name_snapshot or self.status}'


class Voucher(models.Model):
    """A next-visit reward attached to a customer record. Issued by a
    lottery win, a milestone, or a points redemption; consumed by a single
    staff redemption. Never touches the current bill."""

    class Source(models.TextChoices):
        LOTTERY = 'lottery', 'Lottery win'
        MILESTONE = 'milestone', 'Milestone'
        POINTS_REDEEM = 'points_redeem', 'Points redemption'

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        REDEEMED = 'redeemed', 'Redeemed'
        EXPIRED = 'expired', 'Expired'
        VOID = 'void', 'Void'

    customer = models.ForeignKey(
        Customer, on_delete=models.SET_NULL, null=True, related_name='vouchers',
    )
    customer_deleted = models.BooleanField(default=False)
    campaign = models.ForeignKey(Campaign, on_delete=models.PROTECT, related_name='vouchers')
    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.SET_NULL, null=True, related_name='promo_vouchers',
    )
    source = models.CharField(max_length=16, choices=Source.choices)
    source_draw = models.ForeignKey(
        LotteryDraw, on_delete=models.SET_NULL, null=True, blank=True, related_name='vouchers',
    )
    source_milestone = models.ForeignKey(
        Milestone, on_delete=models.SET_NULL, null=True, blank=True, related_name='vouchers',
    )

    reward_type = models.CharField(max_length=16, choices=RewardType.choices)
    # Frozen copy of the prize/milestone reward_config at issue time, plus a
    # human 'label' and (for cash vouchers) 'face_yen'.
    config_snapshot = models.JSONField(default=dict, blank=True)
    min_spend_yen = models.PositiveIntegerField(default=0)
    requires_manual_approval = models.BooleanField(default=False)

    redemption_code = models.CharField(max_length=16, unique=True)
    # Idempotency anchor for a points->voucher redemption (the draw path
    # uses LotteryDraw.request_id instead). Not DB-unique — MySQL can't do
    # a conditional unique — but the per-customer row lock in
    # services.redeem_points serialises redemptions for one customer.
    redeem_request_id = models.CharField(max_length=64, blank=True)
    issued_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    redeemed_at = models.DateTimeField(null=True, blank=True)
    redeemed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    redeemed_branch = models.ForeignKey(
        'branches.Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    redeemed_spend_yen = models.PositiveIntegerField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    void_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-issued_at', '-id']
        indexes = [
            models.Index(fields=['customer', 'status']),
            models.Index(fields=['redemption_code']),
        ]

    def __str__(self):
        return f'{self.redemption_code} ({self.status})'

    @property
    def is_redeemable(self):
        from django.utils import timezone
        return self.status == self.Status.ACTIVE and self.expires_at > timezone.now()


class MilestoneClaim(models.Model):
    """One row the first time a customer reaches a milestone — the guard
    that stops a milestone paying out twice."""

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='milestone_claims')
    milestone = models.ForeignKey(Milestone, on_delete=models.CASCADE, related_name='claims')
    voucher = models.ForeignKey(Voucher, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    lifetime_points_at_claim = models.PositiveIntegerField()
    claimed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-claimed_at']
        constraints = [
            models.UniqueConstraint(
                fields=['customer', 'milestone'], name='unique_promo_milestone_claim',
            ),
        ]


# ---------------------------------------------------------------------------
# Phase 3 — anti-fraud
# ---------------------------------------------------------------------------

class RiskEvent(models.Model):
    """A rule-based flag raised by promotions.risk. A flag is *not* a
    conclusion — it records what tripped the rule, its source, and its
    review state so a manager can look and decide. Never blocks anything on
    its own (the hard rejections live in the services themselves)."""

    class EventType(models.TextChoices):
        OFF_HOURS_VERIFICATION = 'off_hours_verification', 'Off-hours spend confirmation'
        STAFF_RAPID_VERIFICATIONS = 'staff_rapid_verifications', 'Staff confirmed many spends fast'
        AMOUNT_EQUALS_THRESHOLD = 'amount_equals_threshold', 'Amount exactly a voucher threshold'
        CUSTOMER_MULTI_BRANCH = 'customer_multi_branch', 'Same customer across many branches'
        DEVICE_MULTI_REGISTER = 'device_multi_register', 'One device registered many phones'
        CUSTOMER_RAPID_DRAWS = 'customer_rapid_draws', 'Same customer drew many times fast'
        HIGH_VALUE_PRIZE_STREAK = 'high_value_prize_streak', 'Concentrated high-value wins'
        VOIDED_AFTER_REDEMPTION = 'voided_after_redemption', 'Spend voided after value was used'
        PIN_RECOVERY_LOCKOUT = 'pin_recovery_lockout', 'Card PIN recovery locked after repeated failures'

    class Severity(models.TextChoices):
        LOW = 'low', 'Low'
        MEDIUM = 'medium', 'Medium'
        HIGH = 'high', 'High'

    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        REVIEWED = 'reviewed', 'Reviewed — legitimate'
        CONFIRMED = 'confirmed', 'Reviewed — confirmed issue'
        DISMISSED = 'dismissed', 'Dismissed'

    organization = models.ForeignKey(
        'organizations.Organization', on_delete=models.CASCADE, related_name='promo_risk_events',
    )
    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='promo_risk_events',
    )
    customer = models.ForeignKey(
        Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='risk_events',
    )
    staff_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    severity = models.CharField(max_length=8, choices=Severity.choices, default=Severity.MEDIUM)
    # What tripped the rule — the rule name, its threshold, the observed
    # value, and pointers to the rows involved.
    evidence = models.JSONField(default=dict, blank=True)
    source_ref = models.CharField(max_length=64, blank=True)
    # A rule fires once per (type, source_ref) — a repeated evaluation of
    # the same event must not pile up duplicate flags.
    dedupe_key = models.CharField(max_length=128, unique=True)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['organization', 'event_type']),
        ]

    def __str__(self):
        return f'{self.event_type} ({self.severity}) {self.status}'


class StaffPermission(models.Model):
    """Per-account switches for the two staff-facing promotions actions.
    Absent row = both allowed (the phase-1 default). A manager adds a row
    to turn one off for a specific account."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='promo_permission',
    )
    can_verify_spend = models.BooleanField(default=True)
    can_redeem_voucher = models.BooleanField(default=True)
    note = models.CharField(max_length=255, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.user_id}: verify={self.can_verify_spend} redeem={self.can_redeem_voucher}'
