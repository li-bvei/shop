from rest_framework import serializers

from branches.models import Branch

from .models import (
    Campaign, CheckInRecord, Customer, LotteryDraw, Milestone, PointsLedger, Prize, RewardType,
    RiskEvent, SpendVerification, StaffPermission, Voucher,
)
from .services import make_store_token


def _user_name(user):
    if not user:
        return ''
    return user.first_name or user.username


# ---------------------------------------------------------------------------
# Admin / branch
# ---------------------------------------------------------------------------

class CampaignSerializer(serializers.ModelSerializer):
    # Optional on write: a branch account's campaign is pinned to its own
    # branch server-side (CampaignViewSet.perform_create); an admin must
    # name one.
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.all(), required=False)
    branch_name_zh = serializers.CharField(source='branch.name_zh', read_only=True)
    branch_name_ja = serializers.CharField(source='branch.name_ja', read_only=True)
    created_by_name = serializers.SerializerMethodField()
    updated_by_name = serializers.SerializerMethodField()
    store_token = serializers.SerializerMethodField()

    class Meta:
        model = Campaign
        fields = [
            'id', 'branch', 'branch_name_zh', 'branch_name_ja', 'name', 'description', 'status',
            'starts_at', 'ends_at',
            'points_per_1000yen', 'points_per_draw', 'points_per_voucher', 'voucher_yen_per_unit',
            'points_expire_months', 'direct_draw_threshold_yen',
            'max_draws_per_verification', 'max_draws_per_customer_per_day',
            'stamp_target', 'business_day_cutover',
            'created_by_name', 'updated_by_name', 'created_at', 'updated_at', 'store_token',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_created_by_name(self, obj):
        return _user_name(obj.created_by)

    def get_updated_by_name(self, obj):
        return _user_name(obj.updated_by)

    def get_store_token(self, obj):
        """The value the printed store-QR carries — only meaningful once
        the campaign is usable."""
        if obj.status != Campaign.Status.ACTIVE:
            return ''
        return make_store_token(obj)

    def validate(self, attrs):
        starts_at = attrs.get('starts_at', getattr(self.instance, 'starts_at', None))
        ends_at = attrs.get('ends_at', getattr(self.instance, 'ends_at', None))
        if starts_at and ends_at and ends_at < starts_at:
            raise serializers.ValidationError({'ends_at': ['ends-before-starts']})
        return attrs


class PointsLedgerSerializer(serializers.ModelSerializer):
    operator_name = serializers.SerializerMethodField()

    class Meta:
        model = PointsLedger
        fields = ['id', 'delta', 'reason', 'source_ref', 'balance_after', 'note', 'operator_name', 'created_at']

    def get_operator_name(self, obj):
        return _user_name(obj.operator)


class CustomerSerializer(serializers.ModelSerializer):
    """Admin / branch view — full phone (they manage customer data). The
    `card_token` is deliberately NOT exposed: it is the card's bearer
    credential, and nothing in the admin UI acts on it. In-person recovery
    goes through the masked `lookup` action, not the raw token."""

    class Meta:
        model = Customer
        fields = [
            'id', 'phone', 'name', 'birthday_md', 'points_balance',
            'lifetime_points_earned', 'stamp_count', 'draw_chances',
            'status', 'risk_level', 'first_seen_at', 'last_seen_at', 'last_activity_at',
            'privacy_consented_at',
        ]
        read_only_fields = fields


class CustomerDetailSerializer(CustomerSerializer):
    recent_ledger = serializers.SerializerMethodField()
    vouchers = serializers.SerializerMethodField()

    class Meta(CustomerSerializer.Meta):
        fields = CustomerSerializer.Meta.fields + ['recent_ledger', 'vouchers']
        read_only_fields = fields

    def get_recent_ledger(self, obj):
        rows = obj.points_ledger.select_related('operator').all()[:100]
        return PointsLedgerSerializer(rows, many=True).data

    def get_vouchers(self, obj):
        rows = obj.vouchers.all()[:100]
        return VoucherSerializer(rows, many=True).data


class CheckInRecordSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()
    customer_phone = serializers.SerializerMethodField()

    class Meta:
        model = CheckInRecord
        fields = [
            'id', 'customer', 'customer_name', 'customer_phone', 'customer_deleted',
            'branch', 'campaign', 'checked_in_at', 'local_date', 'result', 'risk_level',
        ]
        read_only_fields = fields

    def get_customer_name(self, obj):
        return obj.customer.name if obj.customer else ''

    def get_customer_phone(self, obj):
        return obj.customer.phone_masked if obj.customer else ''


class SpendVerificationSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()
    customer_phone = serializers.SerializerMethodField()
    verified_by_name = serializers.SerializerMethodField()

    class Meta:
        model = SpendVerification
        fields = [
            'id', 'customer', 'customer_name', 'customer_phone', 'customer_deleted',
            'campaign', 'branch', 'table_number', 'amount_yen', 'consumed_at', 'points_granted',
            'direct_draws_granted', 'verified_by_name', 'verified_at', 'status', 'risk_level',
            'voided_at', 'void_reason', 'created_at',
        ]
        read_only_fields = fields

    def get_customer_name(self, obj):
        return obj.customer.name if obj.customer else ''

    def get_customer_phone(self, obj):
        return obj.customer.phone_masked if obj.customer else ''

    def get_verified_by_name(self, obj):
        return _user_name(obj.verified_by)


# ---------------------------------------------------------------------------
# Guest (public, no JWT)
# ---------------------------------------------------------------------------

class GuestRegisterSerializer(serializers.Serializer):
    store_token = serializers.CharField()
    phone = serializers.CharField()
    name = serializers.CharField(required=False, allow_blank=True, default='')
    # Birthday (MM-DD) is required — it's the second factor for recovery and
    # for telling two same-phone cards apart when a chain later federates.
    birthday_md = serializers.CharField()
    pin = serializers.CharField(required=False, allow_blank=True, default='')
    consent = serializers.BooleanField()

    def validate_consent(self, value):
        if value is not True:
            raise serializers.ValidationError('consent-required')
        return value


class GuestLoginSerializer(serializers.Serializer):
    phone = serializers.CharField()
    birthday_md = serializers.CharField()
    # Set only on the second request, after the "which card" picker.
    org = serializers.CharField(required=False, allow_blank=True, default='')


class GuestRecoverSerializer(serializers.Serializer):
    """Full-access recovery — phone + birthday + the 6-digit PIN."""

    phone = serializers.CharField()
    birthday_md = serializers.CharField()
    pin = serializers.CharField()
    org = serializers.CharField(required=False, allow_blank=True, default='')


class GuestSetPinSerializer(serializers.Serializer):
    pin = serializers.CharField()


class GuestRedeemSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=['draw', 'voucher'])
    request_id = serializers.CharField(max_length=64)


class GuestDrawSerializer(serializers.Serializer):
    request_id = serializers.CharField(max_length=64)


# ---------------------------------------------------------------------------
# Phase 2 / 2.5 — prizes, milestones, draws, vouchers
# ---------------------------------------------------------------------------

def validate_reward_config(reward_type, config):
    """Enforce the per-type shape from 开发任务书 §4.8."""
    config = config or {}
    if not isinstance(config, dict):
        raise serializers.ValidationError({'reward_config': ['must-be-an-object']})

    def _pos_int(key, required=True):
        if key not in config:
            if required:
                raise serializers.ValidationError({'reward_config': [f'{key}-required']})
            return
        try:
            value = int(config[key])
        except (TypeError, ValueError):
            raise serializers.ValidationError({'reward_config': [f'{key}-must-be-int']})
        if value < 0:
            raise serializers.ValidationError({'reward_config': [f'{key}-must-be-non-negative']})

    if reward_type == RewardType.CASH_VOUCHER:
        _pos_int('face_yen')
        _pos_int('min_spend_yen', required=False)
    elif reward_type == RewardType.CHEF_SPECIAL:
        _pos_int('menu_value_cap_yen', required=False)
    elif reward_type == RewardType.POINTS_REFUND:
        _pos_int('points')
    # drink / dessert / side_dish: only an optional 'label', nothing to enforce
    return config


class PrizeSerializer(serializers.ModelSerializer):
    probability = serializers.SerializerMethodField()

    class Meta:
        model = Prize
        fields = [
            'id', 'campaign', 'name', 'description', 'display_order', 'weight', 'probability',
            'reward_type', 'reward_config', 'total_stock', 'remaining_stock', 'daily_stock',
            'voucher_expires_after_days', 'voucher_min_spend_yen', 'requires_manual_approval',
            'active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['campaign', 'remaining_stock', 'created_at', 'updated_at']

    def get_probability(self, obj):
        active = [p.weight for p in obj.campaign.prizes.all() if p.active and p.weight > 0]
        total = sum(active)
        return round(obj.weight / total, 4) if (total and obj.active and obj.weight) else 0.0

    def validate(self, attrs):
        reward_type = attrs.get('reward_type', getattr(self.instance, 'reward_type', None))
        config = attrs.get('reward_config', getattr(self.instance, 'reward_config', {}))
        attrs['reward_config'] = validate_reward_config(reward_type, config)
        return attrs


class MilestoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = Milestone
        fields = [
            'id', 'campaign', 'points_threshold', 'reward_type', 'reward_config',
            'voucher_expires_after_days', 'display_label', 'active',
        ]
        read_only_fields = ['campaign']

    def validate(self, attrs):
        reward_type = attrs.get('reward_type', getattr(self.instance, 'reward_type', None))
        if reward_type == RewardType.POINTS_REFUND:
            raise serializers.ValidationError({'reward_type': ['milestone-cannot-be-points-refund']})
        config = attrs.get('reward_config', getattr(self.instance, 'reward_config', {}))
        attrs['reward_config'] = validate_reward_config(reward_type, config)
        return attrs


class LotteryDrawSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()
    customer_phone = serializers.SerializerMethodField()

    class Meta:
        model = LotteryDraw
        fields = [
            'id', 'customer', 'customer_name', 'customer_phone', 'customer_deleted',
            'campaign', 'branch', 'source', 'points_spent', 'prize', 'prize_name_snapshot',
            'reward_type_snapshot', 'weight_snapshot', 'total_weight_snapshot',
            'points_refunded', 'status', 'drawn_at', 'local_date',
        ]
        read_only_fields = fields

    def get_customer_name(self, obj):
        return obj.customer.name if obj.customer else ''

    def get_customer_phone(self, obj):
        return obj.customer.phone_masked if obj.customer else ''


class VoucherSerializer(serializers.ModelSerializer):
    """Admin / staff view."""

    label = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()
    customer_phone = serializers.SerializerMethodField()
    redeemed_by_name = serializers.SerializerMethodField()
    self_service = serializers.SerializerMethodField()

    class Meta:
        model = Voucher
        fields = [
            'id', 'redemption_code', 'label', 'customer', 'customer_name', 'customer_phone',
            'customer_deleted', 'campaign', 'source', 'reward_type', 'config_snapshot',
            'min_spend_yen', 'requires_manual_approval', 'status', 'issued_at', 'expires_at',
            'redeemed_at', 'redeemed_spend_yen', 'redeemed_by_name', 'self_service',
        ]
        read_only_fields = fields

    def get_label(self, obj):
        return obj.config_snapshot.get('label', obj.get_reward_type_display())

    def get_redeemed_by_name(self, obj):
        return _user_name(obj.redeemed_by)

    def get_self_service(self, obj):
        return bool(obj.redeemed_at and obj.redeemed_by_id is None)

    def get_customer_name(self, obj):
        return obj.customer.name if obj.customer else ''

    def get_customer_phone(self, obj):
        return obj.customer.phone_masked if obj.customer else ''


class GuestVoucherSerializer(serializers.ModelSerializer):
    """Customer-facing — no other customer's data, just this voucher."""

    label = serializers.SerializerMethodField()
    reward_type_display = serializers.CharField(source='get_reward_type_display', read_only=True)

    class Meta:
        model = Voucher
        fields = [
            'redemption_code', 'label', 'reward_type', 'reward_type_display', 'source',
            'min_spend_yen', 'requires_manual_approval', 'status', 'issued_at', 'expires_at',
        ]
        read_only_fields = fields

    def get_label(self, obj):
        return obj.config_snapshot.get('label', obj.get_reward_type_display())


# ---------------------------------------------------------------------------
# Phase 3 — risk events, staff permissions
# ---------------------------------------------------------------------------

class RiskEventSerializer(serializers.ModelSerializer):
    event_type_display = serializers.CharField(source='get_event_type_display', read_only=True)
    branch_name_zh = serializers.CharField(source='branch.name_zh', read_only=True, default='')
    customer_name = serializers.SerializerMethodField()
    customer_phone = serializers.SerializerMethodField()
    staff_name = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = RiskEvent
        fields = [
            'id', 'event_type', 'event_type_display', 'severity', 'status', 'evidence', 'source_ref',
            'branch', 'branch_name_zh', 'customer', 'customer_name', 'customer_phone',
            'staff_name', 'reviewed_by_name', 'reviewed_at', 'review_note', 'created_at',
        ]
        read_only_fields = fields

    def get_customer_name(self, obj):
        return obj.customer.name if obj.customer else ''

    def get_customer_phone(self, obj):
        return obj.customer.phone_masked if obj.customer else ''

    def get_staff_name(self, obj):
        return _user_name(obj.staff_user)

    def get_reviewed_by_name(self, obj):
        return _user_name(obj.reviewed_by)


class StaffPermissionSerializer(serializers.ModelSerializer):
    account = serializers.CharField(source='user.username', read_only=True)
    display_name = serializers.SerializerMethodField()
    branch_id = serializers.CharField(source='user.branch_id', read_only=True)

    class Meta:
        model = StaffPermission
        fields = [
            'id', 'user', 'account', 'display_name', 'branch_id',
            'can_verify_spend', 'can_redeem_voucher', 'note', 'updated_at',
        ]
        read_only_fields = ['user', 'updated_at']

    def get_display_name(self, obj):
        return _user_name(obj.user)
