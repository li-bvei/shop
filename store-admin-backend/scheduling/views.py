import django_filters
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from staff.models import StaffMember

from . import attendance
from .models import (
    ActualWorkRecord, AttendanceChangeLog, AttendanceCorrectionRequest, AttendancePunch,
    AvailabilityRequest, BranchScheduleSetting, SchedulePeriod, Shift,
)
from .serializers import (
    ActualWorkRecordSerializer, AttendanceChangeLogSerializer, AttendanceCorrectionRequestSerializer,
    AttendancePunchSerializer, AvailabilityRequestSerializer, BranchScheduleSettingSerializer,
    SchedulePeriodSerializer, ShiftSerializer,
)


class BranchScheduleSettingViewSet(viewsets.ModelViewSet):
    """The shift-time template (morning/afternoon/full-day/off) a branch's
    monthly schedule grid is built from. admin manages every branch in its
    own Organization; branch can only read its own (this is store-level
    operating-hours configuration, not something a single branch account
    should be able to change unilaterally — mirrors BranchViewSet's own
    admin-only write policy). staff never reaches this endpoint at all."""

    serializer_class = BranchScheduleSettingSerializer
    lookup_field = 'branch_id'
    http_method_names = ['get', 'patch', 'head', 'options']

    def get_queryset(self):
        qs = BranchScheduleSetting.objects.select_related('branch')
        user = self.request.user
        if user.role == user.Role.ADMIN:
            return qs.filter(branch__organization_id=user.organization_id)
        return qs.filter(branch_id=user.branch_id)

    def perform_update(self, serializer):
        if self.request.user.role != self.request.user.Role.ADMIN:
            raise PermissionDenied('only admin accounts can change a branch\'s schedule settings.')
        serializer.save()


class SchedulePeriodViewSet(viewsets.ModelViewSet):
    """admin: every branch. branch: its own only, full CRUD + publish.
    staff (opted back into IsAuthenticated): read-only, and only periods
    for its own branch that are open for availability collection or
    already published/closed — a period still being drafted stays hidden
    from staff until the manager publishes it."""

    serializer_class = SchedulePeriodSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['branch', 'status']

    def get_queryset(self):
        qs = SchedulePeriod.objects.select_related('branch')
        user = self.request.user
        if user.role == user.Role.ADMIN:
            return qs.filter(branch__organization_id=user.organization_id)
        if user.role == user.Role.STAFF:
            if not user.staff_member_id:
                return qs.none()
            return qs.filter(
                branch_id=user.branch_id,
                status__in=[SchedulePeriod.Status.COLLECTING, SchedulePeriod.Status.PUBLISHED, SchedulePeriod.Status.CLOSED],
            )
        return qs.filter(branch_id=user.branch_id)

    def _deny_staff_write(self):
        if self.request.user.role == self.request.user.Role.STAFF:
            raise PermissionDenied('read-only for the staff role.')

    def perform_create(self, serializer):
        self._deny_staff_write()
        user = self.request.user
        branch = serializer.validated_data.get('branch')
        if user.role != user.Role.ADMIN:
            if branch and branch.id != user.branch_id:
                raise PermissionDenied('cannot create a schedule period for another branch.')
            try:
                with transaction.atomic():
                    serializer.save(branch_id=user.branch_id, created_by=user)
            except IntegrityError:
                raise ValidationError({'month': ['schedule-period-month-already-exists']})
        else:
            if not branch:
                raise ValidationError({'branch': ['This field is required for admin accounts.']})
            if branch.organization_id != user.organization_id:
                raise PermissionDenied('cannot create a schedule period for another Organization\'s branch.')
            try:
                with transaction.atomic():
                    serializer.save(created_by=user)
            except IntegrityError:
                raise ValidationError({'month': ['schedule-period-month-already-exists']})

    def perform_update(self, serializer):
        self._deny_staff_write()
        instance = serializer.instance
        user = self.request.user
        if user.role != user.Role.ADMIN and instance.branch_id != user.branch_id:
            raise PermissionDenied('cannot modify a schedule period for another branch.')
        serializer.save()

    def perform_destroy(self, instance):
        self._deny_staff_write()
        user = self.request.user
        if user.role != user.Role.ADMIN and instance.branch_id != user.branch_id:
            raise PermissionDenied('cannot delete a schedule period for another branch.')
        instance.delete()

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        self._deny_staff_write()
        period = self.get_object()
        if period.status == SchedulePeriod.Status.PUBLISHED:
            period.version += 1
        elif period.status not in (SchedulePeriod.Status.COLLECTING, SchedulePeriod.Status.DRAFTING):
            raise ValidationError('schedule-period-cannot-publish-from-current-status')
        period.status = SchedulePeriod.Status.PUBLISHED
        period.published_at = timezone.now()
        period.published_by = request.user
        period.save()
        return Response(self.get_serializer(period).data)

    @action(detail=True, methods=['post'])
    def generate_actual_records(self, request, pk=None):
        """Idempotent: existing ActualWorkRecord rows (matched by
        employee+work_date, the model's own unique constraint) are left
        untouched — running this twice never duplicates or overwrites a
        record a manager has already started confirming.

        Deliberately not gated on period.status — actual-work confirmation
        is an internal manager tool staff never sees directly (unlike the
        Shift list itself, which staff only sees once published), so
        keeping it in sync with a draft schedule is safe and lets the
        frontend call this right after every save, not just after publish.

        A record generated straight from a published shift, with no
        deviation, starts pre-confirmed (status=MANAGER_CONFIRMED) instead
        of pending — the act of publishing the shift and bringing it
        forward here already represents a manager's assertion that this is
        the plan, so a normal day needs zero further clicks before it
        counts toward wages (see wages/calculation.py's status filter).
        The manager only has to act on days that turn out different from
        the plan — editing a record to record that difference is itself
        the confirmation (see ActualWorkRecordViewSet.perform_update).

        Each record created here writes an AttendanceChangeLog entry with
        source=GENERATED, in the same transaction — this path pre-confirms
        a day straight into payroll, which is precisely the kind of write
        that has to leave a trail. Records that already existed are skipped
        and produce no entry, since nothing changed."""
        self._deny_staff_write()
        period = self.get_object()
        created = 0
        with transaction.atomic():
            for shift in period.shifts.select_related('employee', 'branch').all():
                record, was_created = ActualWorkRecord.objects.get_or_create(
                    employee=shift.employee, work_date=shift.work_date,
                    defaults={
                        'shift': shift, 'branch': shift.branch,
                        'actual_start': shift.planned_start, 'actual_end': shift.planned_end,
                        'crosses_midnight': shift.crosses_midnight,
                        'actual_break_minutes': shift.planned_break_minutes,
                        'status': ActualWorkRecord.Status.MANAGER_CONFIRMED,
                        'confirmed_by': request.user, 'confirmed_at': timezone.now(),
                        'source': ActualWorkRecord.Source.PLAN,
                    },
                )
                if was_created:
                    created += 1
                    # before=None: the row did not exist until this call.
                    # Inside the same atomic block as the record itself, so
                    # a record can never be committed without its log entry.
                    attendance.log_change(
                        record, source=AttendanceChangeLog.Source.GENERATED, before=None,
                        actor=request.user, reason='generate_actual_records',
                    )
        return Response({'created': created, 'total_shifts': period.shifts.count()})


class AvailabilityRequestViewSet(viewsets.ModelViewSet):
    """admin/branch manage anyone at their scope (mostly used to view what
    staff submitted); staff manages only its own rows."""

    serializer_class = AvailabilityRequestSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['period', 'employee']

    def get_queryset(self):
        qs = AvailabilityRequest.objects.select_related('employee', 'period')
        user = self.request.user
        if user.role == user.Role.ADMIN:
            return qs.filter(employee__branch__organization_id=user.organization_id)
        if user.role == user.Role.STAFF:
            if not user.staff_member_id:
                return qs.none()
            return qs.filter(employee_id=user.staff_member_id)
        return qs.filter(employee__branch_id=user.branch_id)

    def _check_scope(self, employee):
        user = self.request.user
        if user.role == user.Role.STAFF:
            if employee.id != user.staff_member_id:
                raise PermissionDenied('staff can only submit its own availability.')
        elif user.role == user.Role.ADMIN:
            if employee.branch.organization_id != user.organization_id:
                raise PermissionDenied('cannot manage availability for an employee outside your Organization.')
        elif employee.branch_id != user.branch_id:
            raise PermissionDenied('cannot manage availability for an employee outside your branch.')

    def perform_create(self, serializer):
        self._check_scope(serializer.validated_data['employee'])
        serializer.save()

    def perform_update(self, serializer):
        self._check_scope(serializer.instance.employee)
        serializer.save()

    def perform_destroy(self, instance):
        self._check_scope(instance.employee)
        instance.delete()


class ShiftViewSet(viewsets.ModelViewSet):
    """admin: every branch. branch: its own only. staff: read-only, own
    shifts, and only from periods that have actually been published."""

    serializer_class = ShiftSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['period', 'branch', 'employee', 'work_date']

    def get_queryset(self):
        qs = Shift.objects.select_related('employee', 'branch', 'period')
        user = self.request.user
        if user.role == user.Role.ADMIN:
            return qs.filter(branch__organization_id=user.organization_id)
        if user.role == user.Role.STAFF:
            if not user.staff_member_id:
                return qs.none()
            return qs.filter(
                employee_id=user.staff_member_id,
                period__status__in=[SchedulePeriod.Status.PUBLISHED, SchedulePeriod.Status.CLOSED],
            )
        return qs.filter(branch_id=user.branch_id)

    def _deny_staff_write(self):
        if self.request.user.role == self.request.user.Role.STAFF:
            raise PermissionDenied('read-only for the staff role.')

    def _check_branch_scope(self, branch):
        user = self.request.user
        if user.role == user.Role.ADMIN:
            if branch and branch.organization_id != user.organization_id:
                raise PermissionDenied('cannot manage a shift for another Organization\'s branch.')
        elif branch and branch.id != user.branch_id:
            raise PermissionDenied('cannot manage a shift for another branch.')

    def perform_create(self, serializer):
        self._deny_staff_write()
        self._check_branch_scope(serializer.validated_data.get('branch'))
        user = self.request.user
        extra = {'created_by': user, 'updated_by': user}
        if serializer.validated_data.get('override'):
            extra['override_by'] = user
            extra['override_at'] = timezone.now()
        serializer.save(**extra)

    def perform_update(self, serializer):
        self._deny_staff_write()
        instance = serializer.instance
        self._check_branch_scope(serializer.validated_data.get('branch', instance.branch))
        user = self.request.user
        extra = {'updated_by': user}
        if serializer.validated_data.get('override') and not instance.override:
            extra['override_by'] = user
            extra['override_at'] = timezone.now()
        serializer.save(**extra)

    def perform_destroy(self, instance):
        self._deny_staff_write()
        self._check_branch_scope(instance.branch)
        instance.delete()


class ActualWorkRecordFilter(django_filters.FilterSet):
    date_from = django_filters.DateFilter(field_name='work_date', lookup_expr='gte')
    date_to = django_filters.DateFilter(field_name='work_date', lookup_expr='lte')
    # "Only show me the days that need attention" — the single filter a
    # manager reviewing a month actually wants, since the other 90% of days
    # went exactly to plan and need no decision.
    exception = django_filters.BooleanFilter(method='filter_exception')

    class Meta:
        model = ActualWorkRecord
        fields = ['branch', 'employee', 'work_date', 'status', 'source']

    def filter_exception(self, queryset, name, value):
        # An exception is: absent, arrived late, left early, or has times
        # missing (an unfinished punch day). `exception=false` is the
        # complement of exactly that set, not a separate definition, so the
        # two filters always partition the month.
        exceptional = (
            Q(absent=True) | Q(late_minutes__gt=0) | Q(early_leave_minutes__gt=0)
            | Q(absent=False, actual_start__isnull=True) | Q(absent=False, actual_end__isnull=True)
        )
        return queryset.filter(exceptional) if value else queryset.exclude(exceptional)


class ActualWorkRecordViewSet(viewsets.ModelViewSet):
    """admin: confirm/lock/unlock anywhere. branch: confirm only its own
    branch's records, and only while not yet admin_locked. staff: read-only,
    own records — this system has no time-clock hardware, so actual
    times only ever come from a manager's confirmation, never the
    employee's own submission (see the disclaimer text every actual-work
    page must render)."""

    serializer_class = ActualWorkRecordSerializer
    permission_classes = [IsAuthenticated]
    filterset_class = ActualWorkRecordFilter

    def get_queryset(self):
        qs = ActualWorkRecord.objects.select_related('employee', 'branch', 'shift')
        user = self.request.user
        if user.role == user.Role.ADMIN:
            return qs.filter(branch__organization_id=user.organization_id)
        if user.role == user.Role.STAFF:
            if not user.staff_member_id:
                return qs.none()
            return qs.filter(employee_id=user.staff_member_id)
        return qs.filter(branch_id=user.branch_id)

    def _deny_staff_write(self):
        if self.request.user.role == self.request.user.Role.STAFF:
            raise PermissionDenied('read-only for the staff role.')

    def _check_branch_and_lock(self, instance_or_branch, existing_status=None):
        user = self.request.user
        branch = instance_or_branch.branch if hasattr(instance_or_branch, 'branch') else instance_or_branch
        if user.role == user.Role.ADMIN:
            if branch and branch.organization_id != user.organization_id:
                raise PermissionDenied('cannot manage an attendance record for another Organization\'s branch.')
        elif branch and branch.id != user.branch_id:
            raise PermissionDenied('cannot manage an attendance record for another branch.')
        if user.role != user.Role.ADMIN and existing_status == ActualWorkRecord.Status.ADMIN_LOCKED:
            raise PermissionDenied('this record is locked — only admin can unlock it first.')

    def perform_create(self, serializer):
        self._deny_staff_write()
        user = self.request.user
        branch = serializer.validated_data.get('branch')
        if user.role != user.Role.ADMIN:
            branch = user.branch
        self._check_branch_and_lock(branch)
        record = serializer.save(branch=branch, updated_by=user, source=ActualWorkRecord.Source.MANUAL)
        # Deviation from the plan is derived here, never accepted from the
        # client (see the serializer's read_only_fields), and the change is
        # logged like every other write to an attendance record.
        attendance.apply_exception_minutes(record)
        record.save(update_fields=['late_minutes', 'early_leave_minutes'])
        attendance.log_change(
            record, source=AttendanceChangeLog.Source.MANUAL, before=None, actor=user,
            reason=record.adjustment_reason,
        )

    def perform_update(self, serializer):
        self._deny_staff_write()
        instance = serializer.instance
        self._check_branch_and_lock(instance, existing_status=instance.status)
        user = self.request.user
        # Snapshot BEFORE serializer.save() mutates the in-memory instance,
        # otherwise the log's "before" and "after" are the same object and
        # the entry records no change at all.
        before = attendance.snapshot_for_log(instance)
        extra = {'updated_by': user, 'source': ActualWorkRecord.Source.MANUAL}
        # Editing a record (to record an exception — late arrival, absence,
        # extra hours) is itself the confirmation, regardless of role — no
        # separate confirm click needed afterwards. Skipped only when the
        # record is already admin_locked, so an admin correcting a locked
        # record doesn't silently unlock it as a side effect.
        if instance.status != ActualWorkRecord.Status.ADMIN_LOCKED:
            extra['status'] = ActualWorkRecord.Status.MANAGER_CONFIRMED
            extra['confirmed_by'] = user
            extra['confirmed_at'] = timezone.now()
        record = serializer.save(**extra)
        attendance.apply_exception_minutes(record)
        record.save(update_fields=['late_minutes', 'early_leave_minutes'])
        attendance.log_change(
            record, source=AttendanceChangeLog.Source.MANUAL, before=before, actor=user,
            reason=record.adjustment_reason,
        )

    def perform_destroy(self, instance):
        self._deny_staff_write()
        self._check_branch_and_lock(instance, existing_status=instance.status)
        before = attendance.snapshot_for_log(instance)
        employee, branch, work_date = instance.employee, instance.branch, instance.work_date
        instance.delete()
        # record=None: the row is gone, but the log entry must still say
        # which employee/day it described and who removed it.
        attendance.log_change(
            None, source=AttendanceChangeLog.Source.MANUAL, before=before, actor=self.request.user,
            reason='deleted', employee=employee, branch=branch, work_date=work_date,
        )

    @action(detail=False, methods=['post'])
    def bulk_confirm(self, request):
        self._deny_staff_write()
        ids = request.data.get('ids', [])
        qs = self.get_queryset().filter(id__in=ids).exclude(status=ActualWorkRecord.Status.ADMIN_LOCKED)
        # The rows are read before the bulk update so each one's prior
        # status can be logged; confirming is what lets a day into payroll,
        # so it is exactly the kind of change that must leave a trail.
        records = list(qs.select_related('employee', 'branch'))
        befores = {r.id: attendance.snapshot_for_log(r) for r in records}
        updated = qs.update(
            status=ActualWorkRecord.Status.MANAGER_CONFIRMED,
            confirmed_by=request.user, confirmed_at=timezone.now(), updated_by=request.user,
        )
        for record in ActualWorkRecord.objects.filter(id__in=befores.keys()).select_related('employee', 'branch'):
            attendance.log_change(
                record, source=AttendanceChangeLog.Source.STATUS, before=befores[record.id],
                actor=request.user, reason='bulk_confirm',
            )
        return Response({'confirmed': updated})

    @action(detail=True, methods=['post'])
    def lock(self, request, pk=None):
        if request.user.role != request.user.Role.ADMIN:
            raise PermissionDenied('only admin can lock an attendance record.')
        instance = self.get_object()
        before = attendance.snapshot_for_log(instance)
        instance.status = ActualWorkRecord.Status.ADMIN_LOCKED
        instance.updated_by = request.user
        instance.save()
        attendance.log_change(
            instance, source=AttendanceChangeLog.Source.STATUS, before=before,
            actor=request.user, reason='lock',
        )
        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=['post'])
    def unlock(self, request, pk=None):
        if request.user.role != request.user.Role.ADMIN:
            raise PermissionDenied('only admin can unlock an attendance record.')
        reason = (request.data or {}).get('reason', '').strip()
        if not reason:
            raise ValidationError({'reason': ['Required when unlocking an attendance record.']})
        instance = self.get_object()
        before = attendance.snapshot_for_log(instance)
        instance.status = ActualWorkRecord.Status.MANAGER_CONFIRMED
        instance.updated_by = request.user
        instance.adjustment_reason = (instance.adjustment_reason + f' [unlocked: {reason}]').strip()
        instance.save()
        attendance.log_change(
            instance, source=AttendanceChangeLog.Source.STATUS, before=before,
            actor=request.user, reason=f'unlock: {reason}',
        )
        return Response(self.get_serializer(instance).data)


class AttendanceScopedMixin:
    """Tenant + role scoping shared by the three attendance endpoints.

    Three concentric scopes, enforced on the queryset (not merely on
    detail routes), so a list request can never leak a row the caller
    isn't entitled to and a crafted pk simply 404s:
      * admin  — every branch of its OWN Organization, never another's
      * branch — its own branch only
      * staff  — its own rows only, and only if the account is actually
                 linked to a StaffMember
    The frontend hides what a role can't use, but that is cosmetic; this
    is the control.
    """

    def scope_queryset(self, qs):
        user = self.request.user
        if user.role == user.Role.ADMIN:
            return qs.filter(branch__organization_id=user.organization_id)
        if user.role == user.Role.STAFF:
            if not user.staff_member_id:
                return qs.none()
            return qs.filter(employee_id=user.staff_member_id)
        return qs.filter(branch_id=user.branch_id)

    def resolve_employee(self, requested_employee):
        """The StaffMember this write is for, after checking the caller may
        write for them. Staff may only ever act for themselves — the
        request body's `employee` is ignored rather than trusted, so
        submitting someone else's id does nothing instead of succeeding."""
        user = self.request.user
        if user.role == user.Role.STAFF:
            if not user.staff_member_id:
                raise PermissionDenied('this account is not linked to an employee record.')
            return StaffMember.objects.get(pk=user.staff_member_id)
        if requested_employee is None:
            raise ValidationError({'employee': ['This field is required.']})
        if user.role == user.Role.ADMIN:
            if requested_employee.branch.organization_id != user.organization_id:
                raise PermissionDenied('employee belongs to another Organization.')
        elif requested_employee.branch_id != user.branch_id:
            raise PermissionDenied('employee belongs to another branch.')
        return requested_employee


class AttendancePunchFilter(django_filters.FilterSet):
    date_from = django_filters.DateFilter(field_name='work_date', lookup_expr='gte')
    date_to = django_filters.DateFilter(field_name='work_date', lookup_expr='lte')

    class Meta:
        model = AttendancePunch
        fields = ['branch', 'employee', 'work_date', 'kind']


class AttendancePunchViewSet(AttendanceScopedMixin, mixins.CreateModelMixin, mixins.ListModelMixin,
                              mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Clock in / out / break punches.

    Create and read only — no update, no destroy, at any role. A punch is
    the evidence layer under attendance (see scheduling/attendance.py); a
    mistaken punch is answered by another punch and a correction request,
    never by editing history. That is also why `http_method_names` is
    pinned rather than relying on the mixin set alone.

    Staff are opted back in to IsAuthenticated (the project default is
    DenyStaffRole) because clocking oneself in is the entire point; what
    they may do is narrowed by AttendanceScopedMixin instead.
    """

    serializer_class = AttendancePunchSerializer
    permission_classes = [IsAuthenticated]
    filterset_class = AttendancePunchFilter
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        return self.scope_queryset(AttendancePunch.objects.select_related('employee', 'branch'))

    def perform_create(self, serializer):
        user = self.request.user
        employee = self.resolve_employee(serializer.validated_data.get('employee'))
        branch = employee.branch
        setting = attendance.setting_for(branch)

        if user.role == user.Role.STAFF and setting is not None and not setting.self_punch_enabled:
            raise PermissionDenied('self-punch-disabled-for-branch')

        # Server clock only — see AttendancePunchSerializer's read_only_fields.
        now = timezone.now()
        work_date = attendance.business_date_for(branch, now, setting)
        kind = serializer.validated_data['kind']

        error = attendance.next_punch_error(employee, work_date, kind)
        if error:
            raise ValidationError({'kind': [error]})

        source = (
            AttendancePunch.Source.SELF if user.role == user.Role.STAFF
            else AttendancePunch.Source.MANAGER
        )
        serializer.save(
            employee=employee, branch=branch, work_date=work_date, punched_at=now,
            source=source, created_by=user,
        )
        # Keep the day's derived attendance in step with its punches. A day
        # a manager already confirmed is left alone (see is_frozen) — the
        # punch is still stored, it just doesn't overwrite a decision.
        attendance.rebuild_from_punches(employee, branch, work_date, actor=user)

    @action(detail=False, methods=['get'])
    def today(self, request):
        """Which punch the caller may make next, for their own screen.

        Staff get their own state. A manager must name an employee, since
        a manager has no attendance of their own on this endpoint.
        """
        user = request.user
        if user.role == user.Role.STAFF:
            if not user.staff_member_id:
                raise PermissionDenied('this account is not linked to an employee record.')
            employee = StaffMember.objects.get(pk=user.staff_member_id)
        else:
            employee_id = request.query_params.get('employee')
            if not employee_id:
                raise ValidationError({'employee': ['Required for non-staff accounts.']})
            employee = self.resolve_employee(
                StaffMember.objects.filter(pk=employee_id).select_related('branch').first(),
            )
        setting = attendance.setting_for(employee.branch)
        work_date = attendance.business_date_for(employee.branch, timezone.now(), setting)
        state = attendance.open_state(employee, work_date)
        state['employee'] = employee.id
        state['selfPunchEnabled'] = setting.self_punch_enabled if setting else True
        return Response(state)


class AttendanceCorrectionRequestFilter(django_filters.FilterSet):
    date_from = django_filters.DateFilter(field_name='work_date', lookup_expr='gte')
    date_to = django_filters.DateFilter(field_name='work_date', lookup_expr='lte')

    class Meta:
        model = AttendanceCorrectionRequest
        fields = ['branch', 'employee', 'work_date', 'status']


class AttendanceCorrectionRequestViewSet(AttendanceScopedMixin, mixins.CreateModelMixin,
                                          mixins.ListModelMixin, mixins.RetrieveModelMixin,
                                          viewsets.GenericViewSet):
    """補正申請 — an employee's request to fix one day, and a manager's
    decision on it.

    Staff may create their own and withdraw their own while still pending.
    Only branch/admin may approve or reject, and never their own request:
    approving is what lets a correction reach the attendance a wage is
    derived from, so it stays a second pair of eyes.
    """

    serializer_class = AttendanceCorrectionRequestSerializer
    permission_classes = [IsAuthenticated]
    filterset_class = AttendanceCorrectionRequestFilter
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        return self.scope_queryset(
            AttendanceCorrectionRequest.objects.select_related('employee', 'branch'),
        )

    def perform_create(self, serializer):
        user = self.request.user
        employee = self.resolve_employee(serializer.validated_data.get('employee'))
        work_date = serializer.validated_data.get('work_date')
        # One open request per employee per day — checked here, not in the
        # serializer, because this is the first point at which the
        # effective employee is known (a staff account sends no employee
        # id; see the serializer's note).
        already_pending = AttendanceCorrectionRequest.objects.filter(
            employee=employee, work_date=work_date, status=AttendanceCorrectionRequest.Status.PENDING,
        ).exists()
        if already_pending:
            raise ValidationError({'work_date': ['correction-already-pending-for-date']})
        serializer.save(
            employee=employee, branch=employee.branch, submitted_by=user,
            status=AttendanceCorrectionRequest.Status.PENDING,
        )

    def _require_manager(self):
        if self.request.user.role == self.request.user.Role.STAFF:
            raise PermissionDenied('only a branch manager or admin can decide a correction request.')

    def _require_pending(self, correction):
        if correction.status != AttendanceCorrectionRequest.Status.PENDING:
            raise ValidationError({'status': ['correction-already-decided']})

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        self._require_manager()
        correction = self.get_object()
        self._require_pending(correction)
        record, applied = attendance.apply_correction(correction, actor=request.user)
        if not applied:
            # The day is admin-locked: an approval must not silently do
            # nothing, so this is refused with the reason rather than
            # recorded as approved-but-not-applied.
            raise ValidationError({'work_date': ['correction-target-record-locked']})
        correction.status = AttendanceCorrectionRequest.Status.APPROVED
        correction.decided_by = request.user
        correction.decided_at = timezone.now()
        correction.decision_note = str(request.data.get('note', ''))[:255]
        correction.save()
        return Response(self.get_serializer(correction).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        self._require_manager()
        correction = self.get_object()
        self._require_pending(correction)
        note = str(request.data.get('note', '')).strip()
        if not note:
            # An employee is owed a reason; a bare "rejected" is not one.
            raise ValidationError({'note': ['correction-rejection-note-required']})
        correction.status = AttendanceCorrectionRequest.Status.REJECTED
        correction.decided_by = request.user
        correction.decided_at = timezone.now()
        correction.decision_note = note[:255]
        correction.save()
        return Response(self.get_serializer(correction).data)

    @action(detail=True, methods=['post'])
    def withdraw(self, request, pk=None):
        """The submitter takes their own still-pending request back."""
        correction = self.get_object()
        self._require_pending(correction)
        user = request.user
        if user.role == user.Role.STAFF and correction.employee_id != user.staff_member_id:
            raise PermissionDenied('cannot withdraw another employee\'s request.')
        correction.status = AttendanceCorrectionRequest.Status.WITHDRAWN
        correction.decided_by = user
        correction.decided_at = timezone.now()
        correction.save()
        return Response(self.get_serializer(correction).data)


class AttendanceChangeLogFilter(django_filters.FilterSet):
    date_from = django_filters.DateFilter(field_name='work_date', lookup_expr='gte')
    date_to = django_filters.DateFilter(field_name='work_date', lookup_expr='lte')

    class Meta:
        model = AttendanceChangeLog
        fields = ['branch', 'employee', 'work_date', 'record', 'source']


class AttendanceChangeLogViewSet(AttendanceScopedMixin, mixins.ListModelMixin,
                                  mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Read-only audit trail. Append-only by construction: entries are
    written by scheduling.attendance, and there is no create/update/delete
    route here at any role, including admin."""

    serializer_class = AttendanceChangeLogSerializer
    permission_classes = [IsAuthenticated]
    filterset_class = AttendanceChangeLogFilter
    http_method_names = ['get', 'head', 'options']

    def get_queryset(self):
        return self.scope_queryset(
            AttendanceChangeLog.objects.select_related('employee', 'branch', 'changed_by'),
        )
