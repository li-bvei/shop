from django.contrib import admin

from .models import (
    Campaign, CheckInRecord, Customer, LotteryDraw, Milestone, MilestoneClaim, PointsLedger, Prize,
    RiskEvent, SpendVerification, StaffPermission, Voucher,
)


class PrizeInline(admin.TabularInline):
    model = Prize
    extra = 0


class MilestoneInline(admin.TabularInline):
    model = Milestone
    extra = 0


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ['name', 'branch', 'status', 'points_per_1000yen', 'stamp_target', 'created_at']
    list_filter = ['status', 'branch']
    search_fields = ['name']
    inlines = [PrizeInline, MilestoneInline]


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ['name', 'phone', 'organization', 'points_balance', 'stamp_count', 'status', 'last_seen_at']
    list_filter = ['status', 'organization', 'risk_level']
    search_fields = ['phone', 'name', 'card_token']
    readonly_fields = ['card_token', 'points_balance', 'stamp_count', 'first_seen_at']


@admin.register(PointsLedger)
class PointsLedgerAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'customer', 'delta', 'reason', 'balance_after', 'operator']
    list_filter = ['reason']
    search_fields = ['customer__phone', 'customer__name', 'source_ref']
    # Immutable ledger — visible for troubleshooting, never edited here.
    readonly_fields = [f.name for f in PointsLedger._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CheckInRecord)
class CheckInRecordAdmin(admin.ModelAdmin):
    list_display = ['local_date', 'customer', 'branch', 'campaign', 'checked_in_at', 'result']
    list_filter = ['branch', 'result']
    search_fields = ['customer__phone', 'customer__name']


@admin.register(SpendVerification)
class SpendVerificationAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'customer', 'branch', 'amount_yen', 'points_granted', 'status', 'verified_by']
    list_filter = ['status', 'branch']
    search_fields = ['customer__phone', 'customer__name']
    readonly_fields = ['verified_at', 'created_at']


@admin.register(Prize)
class PrizeAdmin(admin.ModelAdmin):
    list_display = ['name', 'campaign', 'reward_type', 'weight', 'remaining_stock', 'daily_stock', 'active']
    list_filter = ['reward_type', 'active', 'campaign']


@admin.register(Milestone)
class MilestoneAdmin(admin.ModelAdmin):
    list_display = ['campaign', 'points_threshold', 'reward_type', 'active']
    list_filter = ['active', 'campaign']


@admin.register(LotteryDraw)
class LotteryDrawAdmin(admin.ModelAdmin):
    list_display = ['drawn_at', 'customer', 'branch', 'source', 'prize_name_snapshot', 'status']
    list_filter = ['status', 'source', 'branch']
    search_fields = ['customer__phone', 'customer__name', 'request_id']
    readonly_fields = [f.name for f in LotteryDraw._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(Voucher)
class VoucherAdmin(admin.ModelAdmin):
    list_display = ['redemption_code', 'customer', 'reward_type', 'source', 'status', 'expires_at']
    list_filter = ['status', 'source', 'reward_type']
    search_fields = ['redemption_code', 'customer__phone', 'customer__name']


@admin.register(MilestoneClaim)
class MilestoneClaimAdmin(admin.ModelAdmin):
    list_display = ['claimed_at', 'customer', 'milestone', 'lifetime_points_at_claim']


@admin.register(RiskEvent)
class RiskEventAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'event_type', 'severity', 'status', 'branch', 'customer', 'staff_user']
    list_filter = ['status', 'severity', 'event_type', 'branch']
    search_fields = ['customer__phone', 'customer__name', 'source_ref']
    readonly_fields = ['dedupe_key', 'evidence', 'source_ref', 'created_at']


@admin.register(StaffPermission)
class StaffPermissionAdmin(admin.ModelAdmin):
    list_display = ['user', 'can_verify_spend', 'can_redeem_voucher', 'updated_at']
    list_filter = ['can_verify_spend', 'can_redeem_voucher']
