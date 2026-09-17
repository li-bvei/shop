from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from .models import PurchaseRecord, Supplier


class SupplierSerializer(serializers.ModelSerializer):
    payable_override = serializers.SerializerMethodField()
    monthly_payable = serializers.SerializerMethodField()

    class Meta:
        model = Supplier
        fields = [
            'id', 'name', 'category', 'contact', 'phone', 'address',
            'bank_name', 'bank_name_furigana', 'branch_name', 'branch_name_furigana',
            'account_type', 'account_number', 'account_holder_furigana',
            'note', 'payable_override', 'monthly_payable',
        ]

    def get_monthly_payable(self, obj):
        override = self.get_payable_override(obj)
        if override is not None:
            return override
        month = self.context.get('payable_month') or timezone.localdate().replace(day=1)
        branch_id = self.context.get('payable_branch_id')
        records = obj.purchase_records.filter(date__year=month.year, date__month=month.month)
        if branch_id:
            records = records.filter(branch_id=branch_id)
        total = records.aggregate(total=Sum('amount'))['total']
        return total or 0

    def get_payable_override(self, obj):
        return self.context.get('payable_overrides', {}).get(obj.id)


class PurchaseRecordSerializer(serializers.ModelSerializer):
    # Populated by the view (list/retrieve) from a bulk-computed lookup
    # passed in via serializer context — never queried per-row here, which
    # would turn a list of 50 records into 50+ extra queries.
    price_direction = serializers.SerializerMethodField()
    prior_month_avg_unit_price = serializers.SerializerMethodField()
    price_delta_amount = serializers.SerializerMethodField()
    price_delta_percent = serializers.SerializerMethodField()
    # A second, separate comparison basis — see
    # purchasing.services.compute_prior_purchase_deltas for why this isn't
    # just derived from the fields above.
    prior_purchase_unit_price = serializers.SerializerMethodField()
    prior_purchase_direction = serializers.SerializerMethodField()
    prior_purchase_delta_amount = serializers.SerializerMethodField()
    prior_purchase_delta_percent = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseRecord
        fields = [
            'id', 'date', 'branch', 'supplier', 'item_name', 'item_name_normalized',
            'quantity', 'unit_price', 'amount', 'note',
            'price_direction', 'prior_month_avg_unit_price',
            'price_delta_amount', 'price_delta_percent',
            'prior_purchase_unit_price', 'prior_purchase_direction',
            'prior_purchase_delta_amount', 'prior_purchase_delta_percent',
        ]
        read_only_fields = ['amount', 'item_name_normalized']
        extra_kwargs = {
            # Branch-role users never submit a branch — BranchScopedQuerysetMixin
            # injects request.user.branch_id in perform_create. Admins still
            # must supply one; that's enforced in the mixin, not here.
            'branch': {'required': False},
        }

    def get_price_direction(self, obj):
        lookup = self.context.get('price_comparisons', {})
        entry = lookup.get(obj.id)
        return entry['direction'] if entry else None

    def get_prior_month_avg_unit_price(self, obj):
        lookup = self.context.get('price_comparisons', {})
        entry = lookup.get(obj.id)
        return entry['prior_avg'] if entry else None

    def get_price_delta_amount(self, obj):
        entry = self.context.get('price_comparisons', {}).get(obj.id)
        return entry['delta_amount'] if entry else None

    def get_price_delta_percent(self, obj):
        entry = self.context.get('price_comparisons', {}).get(obj.id)
        return entry['delta_percent'] if entry else None

    def get_prior_purchase_unit_price(self, obj):
        entry = self.context.get('prior_purchase_deltas', {}).get(obj.id)
        return entry['prior_unit_price'] if entry else None

    def get_prior_purchase_direction(self, obj):
        entry = self.context.get('prior_purchase_deltas', {}).get(obj.id)
        return entry['direction'] if entry else None

    def get_prior_purchase_delta_amount(self, obj):
        entry = self.context.get('prior_purchase_deltas', {}).get(obj.id)
        return entry['delta_amount'] if entry else None

    def get_prior_purchase_delta_percent(self, obj):
        entry = self.context.get('prior_purchase_deltas', {}).get(obj.id)
        return entry['delta_percent'] if entry else None

    def validate(self, attrs):
        instance = self.instance
        branch = attrs.get('branch', instance.branch if instance else None)
        supplier = attrs.get('supplier', instance.supplier if instance else None)
        request = self.context.get('request')
        if not branch and request and request.user.branch_id:
            branch = request.user.branch
        if branch and supplier and branch.organization_id != supplier.organization_id:
            raise serializers.ValidationError({'supplier': ['supplier-outside-organization']})
        return attrs
