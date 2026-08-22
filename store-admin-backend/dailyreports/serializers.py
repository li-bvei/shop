from decimal import Decimal, InvalidOperation

from rest_framework import serializers

from paymentmethods.models import PaymentMethodDef

from .models import DailyReport, DailyReportHistory


class DailyReportSerializer(serializers.ModelSerializer):
    cash_remaining = serializers.SerializerMethodField()
    class Meta:
        model = DailyReport
        fields = [
            'id', 'branch', 'date', 'person_in_charge',
            'total_revenue', 'total_customers', 'group_count',
            'morning_revenue', 'morning_customers', 'morning_group_count',
            'payment_amounts', 'expenses', 'cash_remaining',
            'updated_by', 'updated_at',
        ]
        read_only_fields = ['updated_by', 'updated_at', 'cash_remaining']
        extra_kwargs = {
            # Branch-role users never submit a branch — BranchScopedQuerysetMixin
            # injects request.user.branch_id in perform_create.
            'branch': {'required': False},
        }

    def create(self, validated_data):
        validated_data['updated_by'] = self.context['request'].user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data['updated_by'] = self.context['request'].user
        return super().update(instance, validated_data)

    def _effective_branch(self, attrs):
        if self.instance:
            return self.instance.branch
        branch = attrs.get('branch')
        request = self.context.get('request')
        if not branch and request and request.user.branch_id:
            branch = request.user.branch
        return branch

    def validate(self, attrs):
        branch = self._effective_branch(attrs)
        person = attrs.get('person_in_charge', self.instance.person_in_charge if self.instance else None)
        if person and branch and person.branch_id != branch.id:
            raise serializers.ValidationError({'person_in_charge': ['person-in-charge-branch-mismatch']})

        raw = attrs.get('payment_amounts', self.instance.payment_amounts if self.instance else {}) or {}
        methods = {str(m.id): m for m in PaymentMethodDef.objects.filter(branch=branch)} if branch else {}
        unknown = sorted(set(map(str, raw.keys())) - set(methods))
        if unknown:
            raise serializers.ValidationError({'payment_amounts': [f'unknown-payment-method:{key}' for key in unknown]})
        cleaned = {}
        for key, value in raw.items():
            try:
                amount = Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError):
                raise serializers.ValidationError({'payment_amounts': [f'invalid-amount:{key}']})
            if amount < 0 or amount != amount.to_integral_value():
                raise serializers.ValidationError({'payment_amounts': [f'non-negative-yen-required:{key}']})
            if not methods[str(key)].protected:
                cleaned[str(key)] = int(amount)
        total_revenue = attrs.get('total_revenue', self.instance.total_revenue if self.instance else 0)
        if sum(cleaned.values()) > total_revenue:
            raise serializers.ValidationError({'payment_amounts': ['non-cash-payments-exceed-total-revenue']})
        attrs['payment_amounts'] = cleaned

        expenses = attrs.get('expenses', self.instance.expenses if self.instance else []) or []
        for index, expense in enumerate(expenses):
            try:
                amount = Decimal(str(expense.get('amount', 0)))
            except (InvalidOperation, TypeError, ValueError):
                raise serializers.ValidationError({'expenses': [f'invalid-amount:{index}']})
            if amount < 0:
                raise serializers.ValidationError({'expenses': [f'non-negative-amount-required:{index}']})
        return attrs

    def get_cash_remaining(self, obj):
        cash = PaymentMethodDef.objects.filter(branch=obj.branch, protected=True).first()
        cash_amount = Decimal(str((obj.payment_amounts or {}).get(str(cash.id), 0))) if cash else Decimal(0)
        expenses = sum(Decimal(str(e.get('amount', 0) or 0)) for e in (obj.expenses or []))
        return cash_amount - expenses


class DailyReportHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyReportHistory
        fields = [
            'id', 'branch', 'date', 'saved_at', 'edited_by', 'edited_by_name',
            'person_in_charge', 'total_revenue', 'cash_remaining', 'data',
        ]
        read_only_fields = ['saved_at', 'edited_by', 'edited_by_name']
        extra_kwargs = {'branch': {'required': False}}

    def create(self, validated_data):
        user = self.context['request'].user
        validated_data['edited_by'] = user
        validated_data['edited_by_name'] = user.username
        return super().create(validated_data)

    def validate(self, attrs):
        branch = attrs.get('branch')
        request = self.context.get('request')
        if not branch and request and request.user.branch_id:
            branch = request.user.branch
        person = attrs.get('person_in_charge')
        if person and branch and person.branch_id != branch.id:
            raise serializers.ValidationError({'person_in_charge': ['person-in-charge-branch-mismatch']})
        # A history row is a server-trusted snapshot of the already saved
        # report. Never accept a client-computed cash remainder.
        data = attrs.get('data') or {}
        report = DailyReport.objects.filter(branch=branch, date=attrs.get('date')).first()
        if report:
            cash = PaymentMethodDef.objects.filter(branch=branch, protected=True).first()
            cash_amount = Decimal(str((report.payment_amounts or {}).get(str(cash.id), 0))) if cash else Decimal(0)
            expenses = sum(Decimal(str(e.get('amount', 0) or 0)) for e in (report.expenses or []))
            attrs['total_revenue'] = report.total_revenue
            attrs['cash_remaining'] = cash_amount - expenses
            attrs['person_in_charge'] = report.person_in_charge
            data['paymentAmounts'] = report.payment_amounts
            data['expenses'] = report.expenses
            attrs['data'] = data
        return attrs
