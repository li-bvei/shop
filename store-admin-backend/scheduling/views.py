import django_filters
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import ActualWorkRecord, AvailabilityRequest, BranchScheduleSetting, SchedulePeriod, Shift
from .serializers import (
    ActualWorkRecordSerializer, AvailabilityRequestSerializer, BranchScheduleSettingSerializer,
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
        the confirmation (see ActualWorkRecordViewSet.perform_update)."""
        self._deny_staff_write()
        period = self.get_object()
        created = 0
        with transaction.atomic():
            for shift in period.shifts.select_related('employee', 'branch').all():
                _, was_created = ActualWorkRecord.objects.get_or_create(
                    employee=shift.employee, work_date=shift.work_date,
                    defaults={
                        'shift': shift, 'branch': shift.branch,
                        'actual_start': shift.planned_start, 'actual_end': shift.planned_end,
                        'crosses_midnight': shift.crosses_midnight,
                        'actual_break_minutes': shift.planned_break_minutes,
                        'status': ActualWorkRecord.Status.MANAGER_CONFIRMED,
                        'confirmed_by': request.user, 'confirmed_at': timezone.now(),
                    },
                )
                if was_created:
                    created += 1
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

    class Meta:
        model = ActualWorkRecord
        fields = ['branch', 'employee', 'work_date', 'status']


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
        serializer.save(branch=branch, updated_by=user)

    def perform_update(self, serializer):
        self._deny_staff_write()
        instance = serializer.instance
        self._check_branch_and_lock(instance, existing_status=instance.status)
        user = self.request.user
        extra = {'updated_by': user}
        # Editing a record (to record an exception — late arrival, absence,
        # extra hours) is itself the confirmation, regardless of role — no
        # separate confirm click needed afterwards. Skipped only when the
        # record is already admin_locked, so an admin correcting a locked
        # record doesn't silently unlock it as a side effect.
        if instance.status != ActualWorkRecord.Status.ADMIN_LOCKED:
            extra['status'] = ActualWorkRecord.Status.MANAGER_CONFIRMED
            extra['confirmed_by'] = user
            extra['confirmed_at'] = timezone.now()
        serializer.save(**extra)

    def perform_destroy(self, instance):
        self._deny_staff_write()
        self._check_branch_and_lock(instance, existing_status=instance.status)
        instance.delete()

    @action(detail=False, methods=['post'])
    def bulk_confirm(self, request):
        self._deny_staff_write()
        ids = request.data.get('ids', [])
        qs = self.get_queryset().filter(id__in=ids).exclude(status=ActualWorkRecord.Status.ADMIN_LOCKED)
        updated = qs.update(
            status=ActualWorkRecord.Status.MANAGER_CONFIRMED,
            confirmed_by=request.user, confirmed_at=timezone.now(), updated_by=request.user,
        )
        return Response({'confirmed': updated})

    @action(detail=True, methods=['post'])
    def lock(self, request, pk=None):
        if request.user.role != request.user.Role.ADMIN:
            raise PermissionDenied('only admin can lock an attendance record.')
        instance = self.get_object()
        instance.status = ActualWorkRecord.Status.ADMIN_LOCKED
        instance.updated_by = request.user
        instance.save()
        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=['post'])
    def unlock(self, request, pk=None):
        if request.user.role != request.user.Role.ADMIN:
            raise PermissionDenied('only admin can unlock an attendance record.')
        reason = (request.data or {}).get('reason', '').strip()
        if not reason:
            raise ValidationError({'reason': ['Required when unlocking an attendance record.']})
        instance = self.get_object()
        instance.status = ActualWorkRecord.Status.MANAGER_CONFIRMED
        instance.updated_by = request.user
        instance.adjustment_reason = (instance.adjustment_reason + f' [unlocked: {reason}]').strip()
        instance.save()
        return Response(self.get_serializer(instance).data)
