import calendar

from rest_framework import serializers

from .models import ActualWorkRecord, AvailabilityRequest, BranchScheduleSetting, SchedulePeriod, Shift
from .services import check_shift


class BranchScheduleSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = BranchScheduleSetting
        fields = [
            'id', 'branch', 'morning_start', 'morning_end', 'afternoon_start', 'afternoon_end',
            'full_day_start', 'full_day_end', 'full_day_break_start', 'full_day_break_end',
            'active', 'updated_at',
        ]
        read_only_fields = ['branch']


class SchedulePeriodSerializer(serializers.ModelSerializer):
    """A period is now created by picking branch+month only — `start_date`/
    `end_date` are always server-computed from `month` (the full calendar
    month, correctly handling leap-year February) and never accepted from
    the client. `month` itself is a create-only field: once a period
    exists, its month never changes (create a new period instead).
    `month=None` rows are legacy periods from before this phase — they
    keep their original arbitrary start_date/end_date and are read-only
    history, never created this way again."""

    class Meta:
        model = SchedulePeriod
        fields = [
            'id', 'branch', 'month', 'start_date', 'end_date', 'status',
            'published_at', 'published_by', 'version', 'note',
            'created_by', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'start_date', 'end_date', 'status', 'published_at', 'published_by', 'version', 'created_by',
        ]

    def validate(self, attrs):
        if self.instance is None:
            month = attrs.get('month')
            branch = attrs.get('branch')
            if not branch:
                raise serializers.ValidationError({'branch': ['This field is required.']})
            if not month:
                raise serializers.ValidationError({'month': ['Required — pick a branch and month; the date '
                                                               'range is always computed automatically.']})
            month = month.replace(day=1)
            last_day = calendar.monthrange(month.year, month.month)[1]
            attrs['month'] = month
            attrs['start_date'] = month
            attrs['end_date'] = month.replace(day=last_day)
            if SchedulePeriod.objects.filter(branch=branch, month=month).exists():
                raise serializers.ValidationError({'month': ['schedule-period-month-already-exists']})
        else:
            if 'month' in attrs and attrs['month'] != self.instance.month:
                raise serializers.ValidationError({'month': ['month cannot be changed after creation.']})
            if 'branch' in attrs and attrs['branch'] != self.instance.branch:
                raise serializers.ValidationError({'branch': ['branch cannot be changed after creation.']})
        return attrs


class AvailabilityRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = AvailabilityRequest
        fields = [
            'id', 'period', 'employee', 'work_date', 'availability',
            'start_time', 'end_time', 'crosses_midnight', 'note', 'created_at', 'updated_at',
        ]

    def validate(self, attrs):
        if self.instance:
            for field in ('period', 'employee', 'work_date'):
                if field in attrs and attrs[field] != getattr(self.instance, field):
                    raise serializers.ValidationError({field: ['availability-identity-field-immutable']})
        availability = attrs.get('availability', self.instance.availability if self.instance else None)
        start_time = attrs.get('start_time', self.instance.start_time if self.instance else None)
        end_time = attrs.get('end_time', self.instance.end_time if self.instance else None)
        if availability == AvailabilityRequest.Availability.AVAILABLE and not (start_time and end_time):
            raise serializers.ValidationError({'start_time': ['Required when availability is "available".']})

        period = attrs.get('period', self.instance.period if self.instance else None)
        employee = attrs.get('employee', self.instance.employee if self.instance else None)
        work_date = attrs.get('work_date', self.instance.work_date if self.instance else None)
        if period and employee and period.branch_id != employee.branch_id:
            raise serializers.ValidationError({'employee': ['availability-employee-period-branch-mismatch']})
        if period and work_date and not (period.start_date <= work_date <= period.end_date):
            raise serializers.ValidationError({'work_date': ['availability-date-outside-period']})
        if period and period.status in (period.Status.PUBLISHED, period.Status.CLOSED):
            request = self.context.get('request')
            user = request.user if request else None
            if user and user.role == user.Role.STAFF:
                raise serializers.ValidationError('availability-locked-after-publish')
        return attrs


class ShiftSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shift
        fields = [
            'id', 'period', 'branch', 'employee', 'work_date', 'planned_start', 'planned_end',
            'crosses_midnight', 'planned_break_minutes', 'position', 'note',
            'override', 'override_reason', 'override_by', 'override_at',
            'created_by', 'updated_by', 'created_at', 'updated_at',
        ]
        read_only_fields = ['override_by', 'override_at', 'created_by', 'updated_by']

    def validate(self, attrs):
        instance = self.instance
        employee = attrs.get('employee', instance.employee if instance else None)
        branch = attrs.get('branch', instance.branch if instance else None)
        period = attrs.get('period', instance.period if instance else None)
        work_date = attrs.get('work_date', instance.work_date if instance else None)
        planned_start = attrs.get('planned_start', instance.planned_start if instance else None)
        planned_end = attrs.get('planned_end', instance.planned_end if instance else None)
        crosses_midnight = attrs.get('crosses_midnight', instance.crosses_midnight if instance else False)
        planned_break_minutes = attrs.get(
            'planned_break_minutes', instance.planned_break_minutes if instance else 0,
        )
        override = attrs.get('override', instance.override if instance else False)

        hard_errors, soft_warnings = check_shift(
            employee, branch, work_date, planned_start, planned_end, crosses_midnight,
            planned_break_minutes, period, exclude_pk=instance.pk if instance else None,
        )
        if hard_errors:
            raise serializers.ValidationError({'code': 'shift-conflict', 'errors': hard_errors})
        if soft_warnings and not override:
            raise serializers.ValidationError({'code': 'requires-override', 'warnings': soft_warnings})
        if override:
            override_reason = attrs.get('override_reason', instance.override_reason if instance else '')
            if not override_reason.strip():
                raise serializers.ValidationError({'override_reason': ['Required when overriding a warning.']})
        return attrs


class ActualWorkRecordSerializer(serializers.ModelSerializer):
    # Read-only view of what was actually scheduled, sourced through the FK
    # rather than duplicated onto this model — lets the frontend show
    # "scheduled 09:00-13:00" next to the actual-time editor so a manager
    # correcting a late arrival can see what they're correcting against,
    # instead of editing blind. None when the record has no linked shift
    # (e.g. created ad hoc rather than via generate_actual_records).
    planned_start = serializers.TimeField(source='shift.planned_start', read_only=True, default=None)
    planned_end = serializers.TimeField(source='shift.planned_end', read_only=True, default=None)
    planned_break_minutes = serializers.IntegerField(source='shift.planned_break_minutes', read_only=True, default=None)
    planned_crosses_midnight = serializers.BooleanField(source='shift.crosses_midnight', read_only=True, default=None)

    class Meta:
        model = ActualWorkRecord
        fields = [
            'id', 'shift', 'branch', 'employee', 'work_date', 'actual_start', 'actual_end',
            'crosses_midnight', 'actual_break_minutes', 'absent', 'statutory_holiday',
            'adjustment_reason', 'status', 'confirmed_by', 'confirmed_at',
            'planned_start', 'planned_end', 'planned_break_minutes', 'planned_crosses_midnight',
            'updated_by', 'updated_at', 'created_at',
        ]
        read_only_fields = ['status', 'confirmed_by', 'confirmed_at', 'updated_by']

    def validate(self, attrs):
        instance = self.instance
        shift = attrs.get('shift', instance.shift if instance else None)
        branch = attrs.get('branch', instance.branch if instance else None)
        employee = attrs.get('employee', instance.employee if instance else None)
        work_date = attrs.get('work_date', instance.work_date if instance else None)
        if instance:
            immutable = {
                'branch': instance.branch, 'employee': instance.employee,
                'shift': instance.shift, 'work_date': instance.work_date,
            }
            for field, original in immutable.items():
                if field in attrs and attrs[field] != original:
                    raise serializers.ValidationError({field: ['actual-work-identity-field-immutable']})
        if branch and employee and employee.branch_id != branch.id:
            raise serializers.ValidationError({'employee': ['actual-work-employee-branch-mismatch']})
        if shift:
            if shift.employee_id != getattr(employee, 'id', None):
                raise serializers.ValidationError({'shift': ['actual-work-shift-employee-mismatch']})
            if shift.branch_id != getattr(branch, 'id', None):
                raise serializers.ValidationError({'shift': ['actual-work-shift-branch-mismatch']})
            if shift.work_date != work_date:
                raise serializers.ValidationError({'shift': ['actual-work-shift-date-mismatch']})
            if shift.period.branch_id != shift.branch_id:
                raise serializers.ValidationError({'shift': ['actual-work-shift-period-branch-mismatch']})
        absent = attrs.get('absent', instance.absent if instance else False)
        if not absent:
            actual_start = attrs.get('actual_start', instance.actual_start if instance else None)
            actual_end = attrs.get('actual_end', instance.actual_end if instance else None)
            crosses_midnight = attrs.get('crosses_midnight', instance.crosses_midnight if instance else False)
            actual_break_minutes = attrs.get(
                'actual_break_minutes', instance.actual_break_minutes if instance else 0,
            )
            if not actual_start or not actual_end:
                raise serializers.ValidationError({'actual_start': ['actual-start-and-end-required']})
            start_minutes = actual_start.hour * 60 + actual_start.minute
            end_minutes = actual_end.hour * 60 + actual_end.minute + (1440 if crosses_midnight else 0)
            if end_minutes <= start_minutes:
                raise serializers.ValidationError({'actual_end': ['actual-end-must-be-after-start']})
            if actual_break_minutes > end_minutes - start_minutes:
                raise serializers.ValidationError({'actual_break_minutes': ['actual-break-exceeds-duration']})
            differs = bool(shift) and (
                actual_start != shift.planned_start or actual_end != shift.planned_end
                or crosses_midnight != shift.crosses_midnight
                or actual_break_minutes != shift.planned_break_minutes
            )
            adjustment_reason = attrs.get('adjustment_reason', instance.adjustment_reason if instance else '')
            if differs and not adjustment_reason.strip():
                raise serializers.ValidationError(
                    {'adjustment_reason': ['Required when actual times differ from the scheduled shift.']},
                )
        return attrs
