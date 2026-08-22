from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from wages.models import WageRule
from wages.services import wage_rule_is_locked

from .models import StaffMember, StaffTransfer


class StaffMemberSerializer(serializers.ModelSerializer):
    """Deliberately excludes wage rules and any wage amount — those live on
    the separate wages app models/endpoints, reachable only by admin (and
    branch, scoped to its own employees), never by a general staff list
    consumer."""

    wage_setting = serializers.JSONField(required=False, allow_null=True)

    class Meta:
        model = StaffMember
        fields = [
            'id', 'name', 'branch', 'role', 'work_area', 'phone', 'status',
            'employment_type', 'hire_date', 'leave_date', 'note', 'wage_setting',
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        rule = instance.wage_rules.order_by('-effective_from').first()
        data['wage_setting'] = None if rule is None else {
            'hourly_rate': rule.hourly_rate,
            'transportation_amount': rule.transportation_amount,
            'effective_from': rule.effective_from,
            'note': rule.note,
        }
        return data

    def validate_wage_setting(self, value):
        if value is None:
            return value
        required = {'hourly_rate', 'transportation_amount'}
        if not required.issubset(value):
            raise serializers.ValidationError('hourly_rate-and-transportation_amount-required')
        try:
            if int(value['hourly_rate']) <= 0 or int(value['transportation_amount']) < 0:
                raise ValueError
        except (TypeError, ValueError):
            raise serializers.ValidationError('wage-setting-amount-invalid')
        return value

    @transaction.atomic
    def _save_wage_setting(self, employee, setting):
        if setting is None:
            return
        if employee.employment_type not in (
            employee.EmploymentType.HOURLY, employee.EmploymentType.TEMPORARY,
        ):
            return
        effective_from = setting.get('effective_from') or employee.hire_date or timezone.localdate()
        if isinstance(effective_from, str):
            effective_from = serializers.DateField().to_internal_value(effective_from)
        latest = employee.wage_rules.select_for_update().order_by('-effective_from').first()
        request = self.context.get('request')
        if latest and latest.effective_from == effective_from:
            if wage_rule_is_locked(latest):
                raise serializers.ValidationError({'wage_setting': ['wage-rule-referenced-by-locked-month']})
            latest.hourly_rate = setting['hourly_rate']
            latest.transportation_type = WageRule.TransportationType.MONTHLY
            latest.transportation_amount = setting['transportation_amount']
            latest.note = setting.get('note', '')
            latest.save()
            return
        if latest and (latest.effective_to is None or latest.effective_to >= effective_from):
            if latest.effective_from >= effective_from:
                raise serializers.ValidationError({'wage_setting': ['effective-date-must-follow-current-rule']})
            if wage_rule_is_locked(latest):
                # Ending a rule after the last locked day is safe, but changing
                # a range which already supplied a locked month is not.
                last_locked = latest.daily_details.filter(
                    result__closing__status='locked',
                ).order_by('-work_date').values_list('work_date', flat=True).first()
                if last_locked and effective_from <= last_locked:
                    raise serializers.ValidationError({'wage_setting': ['wage-rule-referenced-by-locked-month']})
            latest.effective_to = effective_from - timedelta(days=1)
            latest.save(update_fields=['effective_to', 'updated_at'])
        WageRule.objects.create(
            employee=employee, effective_from=effective_from,
            hourly_rate=setting['hourly_rate'],
            transportation_type=WageRule.TransportationType.MONTHLY,
            transportation_amount=setting['transportation_amount'],
            note=setting.get('note', ''),
            created_by=getattr(request, 'user', None),
        )

    def create(self, validated_data):
        setting = validated_data.pop('wage_setting', None)
        employee = super().create(validated_data)
        self._save_wage_setting(employee, setting)
        return employee

    def update(self, instance, validated_data):
        marker = object()
        setting = validated_data.pop('wage_setting', marker)
        employee = super().update(instance, validated_data)
        if setting is not marker:
            self._save_wage_setting(employee, setting)
        return employee


class StaffTransferSerializer(serializers.ModelSerializer):
    """`organization`, `from_branch`, and `changed_by` are never
    client-writable — StaffTransferViewSet.perform_create derives
    `organization`/`from_branch` from the employee's current state and
    `changed_by` from the request, so a client can't backdate or spoof
    which branch an employee was actually moving from."""

    employee_name = serializers.CharField(source='employee.name', read_only=True)
    from_branch_name = serializers.CharField(source='from_branch.name_zh', read_only=True)
    to_branch_name = serializers.CharField(source='to_branch.name_zh', read_only=True)
    changed_by_name = serializers.CharField(source='changed_by.username', read_only=True, default=None)

    class Meta:
        model = StaffTransfer
        fields = [
            'id', 'employee', 'employee_name', 'from_branch', 'from_branch_name',
            'to_branch', 'to_branch_name', 'effective_date', 'reason',
            'changed_by', 'changed_by_name', 'changed_at',
        ]
        read_only_fields = ['from_branch', 'changed_by', 'changed_at']
