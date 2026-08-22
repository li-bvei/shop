import calendar

from rest_framework import serializers

from .models import WageDailyDetail, WageEmployeeResult, WageMonthlyClosing, WageRule


class WageRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = WageRule
        fields = [
            'id', 'employee', 'effective_from', 'effective_to', 'hourly_rate',
            'night_premium_rate', 'overtime_premium_rate', 'statutory_holiday_premium_rate',
            'transportation_type', 'transportation_amount', 'note',
            'created_by', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_by', 'created_at', 'updated_at']

    def validate(self, attrs):
        effective_from = attrs.get('effective_from', self.instance.effective_from if self.instance else None)
        effective_to = attrs.get('effective_to', self.instance.effective_to if self.instance else None)
        if effective_to and effective_from and effective_to < effective_from:
            raise serializers.ValidationError({'effective_to': ['Must not be before effective_from.']})
        return attrs


class WageDailyDetailSerializer(serializers.ModelSerializer):
    # Sourced through the FK rather than duplicated onto WageDailyDetail —
    # single source of truth stays on ActualWorkRecord. DRF's dotted
    # source returns None automatically if actual_work_record is null
    # (e.g. a since-deleted attendance record), no extra guard needed.
    actual_start = serializers.TimeField(source='actual_work_record.actual_start', read_only=True, default=None)
    actual_end = serializers.TimeField(source='actual_work_record.actual_end', read_only=True, default=None)
    actual_break_minutes = serializers.IntegerField(
        source='actual_work_record.actual_break_minutes', read_only=True, default=None,
    )

    class Meta:
        model = WageDailyDetail
        fields = [
            'id', 'work_date', 'actual_work_record', 'wage_rule',
            'actual_start', 'actual_end', 'actual_break_minutes',
            'total_minutes', 'regular_minutes', 'night_minutes', 'overtime_minutes',
            'statutory_holiday_minutes', 'base_amount', 'night_premium', 'overtime_premium',
            'holiday_premium', 'transportation_amount',
        ]


class WageEmployeeResultSerializer(serializers.ModelSerializer):
    daily_details = WageDailyDetailSerializer(many=True, read_only=True)
    employee_name = serializers.CharField(source='employee.name', read_only=True)
    # Staff can read its own results but has no access to the closings
    # endpoint at all (DenyStaffRole), so the month/branch/status it needs
    # to make sense of "which payslip is this" has to ride along here.
    closing_month = serializers.DateField(source='closing.month', read_only=True)
    closing_status = serializers.CharField(source='closing.status', read_only=True)
    closing_branch_id = serializers.CharField(source='closing.branch_id', read_only=True)
    closing_branch_name = serializers.CharField(source='closing.branch.name_zh', read_only=True)
    hourly_rate = serializers.SerializerMethodField()

    class Meta:
        model = WageEmployeeResult
        fields = [
            'id', 'closing', 'closing_month', 'closing_status', 'closing_branch_id', 'closing_branch_name',
            'employee', 'employee_name', 'employment_type',
            'attendance_days', 'total_minutes', 'regular_minutes', 'night_minutes',
            'overtime_minutes', 'statutory_holiday_minutes',
            'hourly_rate', 'base_amount', 'night_premium', 'overtime_premium', 'holiday_premium',
            'transportation_amount', 'manual_addition', 'manual_deduction', 'adjustment_reason',
            'monthly_transportation_override', 'rule_transportation_amount', 'transportation_override_reason',
            'transportation_override_by', 'transportation_override_at',
            'bonus_amount', 'bonus_note', 'bonus_updated_by', 'bonus_updated_at',
            'calculation_period_start', 'calculation_period_end',
            'estimated_total', 'calculation_version', 'daily_details',
            'created_at', 'updated_at',
        ]

    def get_fields(self):
        # Every field is server-computed by the wage engine except the
        # ones a branch/admin can annotate: the legacy v1 manual-adjustment
        # trio, and v2_simple's transportation override / bonus / special
        # calculation period.
        fields = super().get_fields()
        editable = {
            'manual_addition', 'manual_deduction', 'adjustment_reason',
            'monthly_transportation_override', 'transportation_override_reason',
            'bonus_amount', 'bonus_note',
            'calculation_period_start', 'calculation_period_end',
        }
        for name, field in fields.items():
            if name not in editable and name != 'daily_details':
                field.read_only = True
        return fields

    def get_hourly_rate(self, obj):
        detail = obj.daily_details.exclude(wage_rule__isnull=True).select_related('wage_rule').first()
        if detail and detail.wage_rule:
            return detail.wage_rule.hourly_rate
        rule = obj.employee.wage_rules.filter(
            effective_from__lte=obj.calculation_period_end or obj.closing.month.replace(
                day=calendar.monthrange(obj.closing.month.year, obj.closing.month.month)[1],
            ),
        ).order_by('-effective_from').first()
        return rule.hourly_rate if rule else None

    def validate(self, attrs):
        instance = self.instance
        bonus_amount = attrs.get('bonus_amount', instance.bonus_amount if instance else 0)
        bonus_note = attrs.get('bonus_note', instance.bonus_note if instance else '')
        if bonus_amount and not bonus_note.strip():
            raise serializers.ValidationError({'bonus_note': ['Required when bonus_amount is non-zero.']})
        if bonus_amount < 0:
            raise serializers.ValidationError({'bonus_amount': ['Must be non-negative.']})
        transportation = attrs.get(
            'monthly_transportation_override', instance.monthly_transportation_override if instance else None,
        )
        if transportation is not None and transportation < 0:
            raise serializers.ValidationError({'monthly_transportation_override': ['Must be non-negative.']})

        period_start = attrs.get(
            'calculation_period_start', instance.calculation_period_start if instance else None,
        )
        period_end = attrs.get('calculation_period_end', instance.calculation_period_end if instance else None)
        if bool(period_start) != bool(period_end):
            raise serializers.ValidationError(
                {'calculation_period_start': ['Start and end must both be set or both be cleared.']},
            )
        if period_start and period_end and period_end < period_start:
            raise serializers.ValidationError(
                {'calculation_period_end': ['Must not be before calculation_period_start.']},
            )
        if (period_start or period_end) and instance is not None:
            month_start = instance.closing.month
            month_end = month_start.replace(day=calendar.monthrange(month_start.year, month_start.month)[1])
            for label, value in (('calculation_period_start', period_start), ('calculation_period_end', period_end)):
                if value and not (month_start <= value <= month_end):
                    raise serializers.ValidationError({label: ['Must fall within the closing\'s own month.']})
        return attrs


class WageMonthlyClosingSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name_zh', read_only=True)
    employee_results = WageEmployeeResultSerializer(many=True, read_only=True)

    class Meta:
        model = WageMonthlyClosing
        fields = [
            'id', 'branch', 'branch_name', 'month', 'status',
            'confirmed_by', 'confirmed_at', 'locked_by', 'locked_at',
            'unlocked_by', 'unlocked_at', 'unlock_reason', 'version',
            'employee_results', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'status', 'confirmed_by', 'confirmed_at', 'locked_by', 'locked_at',
            'unlocked_by', 'unlocked_at', 'unlock_reason', 'version',
        ]
