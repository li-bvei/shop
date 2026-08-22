from django.db import transaction
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .calculation import DISCLAIMER, find_missing_wage_rule_days, generate_wage_results, month_bounds
from .models import WageEmployeeResult, WageMonthlyClosing, WageRule
from .serializers import WageEmployeeResultSerializer, WageMonthlyClosingSerializer, WageRuleSerializer
from .services import check_calculation_freshness, check_no_period_overlap, wage_rule_is_locked


class WageRuleViewSet(viewsets.ModelViewSet):
    """admin manages every employee's rules; branch is scoped to employees
    at its own branch. staff never reaches this endpoint at all (blocked
    by the project-wide DenyStaffRole default) — wage rules themselves are
    never exposed to the employee they apply to, only the resulting
    computed amounts (via WageEmployeeResultViewSet's own-record filter)."""

    serializer_class = WageRuleSerializer

    def get_queryset(self):
        qs = WageRule.objects.select_related('employee').all()
        user = self.request.user
        if user.role == user.Role.ADMIN:
            return qs.filter(employee__branch__organization_id=user.organization_id)
        return qs.filter(employee__branch_id=user.branch_id)

    def _check_branch_scope(self, employee):
        user = self.request.user
        if user.role == user.Role.ADMIN:
            if employee.branch.organization_id != user.organization_id:
                raise PermissionDenied('cannot manage a wage rule for an employee outside your Organization.')
        elif employee.branch_id != user.branch_id:
            raise PermissionDenied('cannot manage a wage rule for an employee outside your branch.')

    def perform_create(self, serializer):
        employee = serializer.validated_data['employee']
        self._check_branch_scope(employee)
        with transaction.atomic():
            check_no_period_overlap(
                employee.id, serializer.validated_data['effective_from'],
                serializer.validated_data.get('effective_to'),
            )
            serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        instance = serializer.instance
        self._check_branch_scope(instance.employee)
        if wage_rule_is_locked(instance):
            raise ValidationError('wage-rule-referenced-by-locked-month')
        employee = serializer.validated_data.get('employee', instance.employee)
        self._check_branch_scope(employee)
        with transaction.atomic():
            check_no_period_overlap(
                employee.id,
                serializer.validated_data.get('effective_from', instance.effective_from),
                serializer.validated_data.get('effective_to', instance.effective_to),
                exclude_pk=instance.pk,
            )
            serializer.save()

    def perform_destroy(self, instance):
        self._check_branch_scope(instance.employee)
        if wage_rule_is_locked(instance):
            raise ValidationError('wage-rule-referenced-by-locked-month')
        instance.delete()


class WageMonthlyClosingViewSet(viewsets.ModelViewSet):
    """admin operates on every branch; branch is scoped to its own. staff
    never reaches this (see WageEmployeeResultViewSet for its own
    read-only view of just its own results)."""

    serializer_class = WageMonthlyClosingSerializer
    filterset_fields = ['branch', 'status']
    http_method_names = ['get', 'post', 'head', 'options']  # no raw PATCH/PUT — state changes go through actions

    def get_queryset(self):
        qs = WageMonthlyClosing.objects.select_related('branch').prefetch_related(
            'employee_results__daily_details',
        )
        user = self.request.user
        if user.role == user.Role.ADMIN:
            return qs.filter(branch__organization_id=user.organization_id)
        return qs.filter(branch_id=user.branch_id)

    def perform_create(self, serializer):
        user = self.request.user
        branch = serializer.validated_data.get('branch')
        if user.role != user.Role.ADMIN:
            if branch and branch.id != user.branch_id:
                raise PermissionDenied('cannot create a wage closing for another branch.')
            serializer.save(branch_id=user.branch_id, month=serializer.validated_data['month'].replace(day=1))
        else:
            if not branch:
                raise ValidationError({'branch': ['This field is required for admin accounts.']})
            if branch.organization_id != user.organization_id:
                raise PermissionDenied('cannot create a wage closing for another Organization\'s branch.')
            serializer.save(month=serializer.validated_data['month'].replace(day=1))

    @action(detail=True, methods=['post'])
    def generate(self, request, pk=None):
        """(Re)computes results from ActualWorkRecord. Only while draft —
        once confirmed/locked, results are frozen; use unlock first."""
        closing = self.get_object()
        if closing.status != WageMonthlyClosing.Status.DRAFT:
            raise ValidationError('wage-closing-not-draft')
        generate_wage_results(closing)
        closing.last_generated_at = timezone.now()
        closing.save(update_fields=['last_generated_at'])
        closing.refresh_from_db()
        return Response(self.get_serializer(closing).data)

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """Refuses to confirm a closing that was never generated, or whose
        stored results might not reflect a later attendance edit or wage
        rate change — the caller must re-run `generate` first in either
        case, never silently confirm stale/empty numbers."""
        closing = self.get_object()
        if closing.status != WageMonthlyClosing.Status.DRAFT:
            raise ValidationError('wage-closing-not-draft')
        stale_reason = check_calculation_freshness(closing)
        if stale_reason:
            return Response({'code': stale_reason}, status=400)
        missing = find_missing_wage_rule_days(closing)
        if missing:
            return Response(
                {'code': 'missing-wage-rule', 'missing': [
                    {'employee': name, 'date': d.isoformat()} for name, d in missing
                ]},
                status=400,
            )
        with transaction.atomic():
            closing = WageMonthlyClosing.objects.select_for_update().get(pk=closing.pk)
            if closing.status != WageMonthlyClosing.Status.DRAFT:
                raise ValidationError('wage-closing-not-draft')
            # Re-check freshness inside the lock — a confirming request and a
            # record-edit request racing each other must not both succeed.
            stale_reason = check_calculation_freshness(closing)
            if stale_reason:
                return Response({'code': stale_reason}, status=400)
            closing.status = WageMonthlyClosing.Status.CONFIRMED
            closing.confirmed_by = request.user
            closing.confirmed_at = timezone.now()
            closing.save()
        return Response(self.get_serializer(closing).data)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def lock(self, request, pk=None):
        if request.user.role != request.user.Role.ADMIN:
            raise PermissionDenied('only admin can lock a wage month.')
        closing = self.get_object()
        with transaction.atomic():
            closing = WageMonthlyClosing.objects.select_for_update().get(pk=closing.pk)
            if closing.status != WageMonthlyClosing.Status.CONFIRMED:
                raise ValidationError('wage-closing-not-confirmed')
            closing.status = WageMonthlyClosing.Status.LOCKED
            closing.locked_by = request.user
            closing.locked_at = timezone.now()
            closing.version += 1
            closing.save()
        return Response(self.get_serializer(closing).data)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def unconfirm(self, request, pk=None):
        """Symmetric to `unlock`, but for a closing that was confirmed and
        never locked yet — without this, an admin who confirms before
        finishing bonus/transportation entry has no way back to draft."""
        if request.user.role != request.user.Role.ADMIN:
            raise PermissionDenied('only admin can unconfirm a wage month.')
        reason = (request.data or {}).get('reason', '').strip()
        if not reason:
            raise ValidationError({'reason': ['Required when unconfirming a wage month.']})
        closing = self.get_object()
        with transaction.atomic():
            closing = WageMonthlyClosing.objects.select_for_update().get(pk=closing.pk)
            if closing.status != WageMonthlyClosing.Status.CONFIRMED:
                raise ValidationError('wage-closing-not-confirmed')
            closing.status = WageMonthlyClosing.Status.DRAFT
            closing.unlocked_by = request.user
            closing.unlocked_at = timezone.now()
            closing.unlock_reason = reason
            closing.save()
        return Response(self.get_serializer(closing).data)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def unlock(self, request, pk=None):
        if request.user.role != request.user.Role.ADMIN:
            raise PermissionDenied('only admin can unlock a wage month.')
        reason = (request.data or {}).get('reason', '').strip()
        if not reason:
            raise ValidationError({'reason': ['Required when unlocking a locked wage month.']})
        closing = self.get_object()
        with transaction.atomic():
            closing = WageMonthlyClosing.objects.select_for_update().get(pk=closing.pk)
            if closing.status != WageMonthlyClosing.Status.LOCKED:
                raise ValidationError('wage-closing-not-locked')
            closing.status = WageMonthlyClosing.Status.DRAFT
            closing.unlocked_by = request.user
            closing.unlocked_at = timezone.now()
            closing.unlock_reason = reason
            closing.version += 1
            closing.save()
        return Response(self.get_serializer(closing).data)


class WageEmployeeResultViewSet(viewsets.ModelViewSet):
    """Read-only for everyone in practice (only `manual_addition`/
    `manual_deduction`/`adjustment_reason` are writable, and only while the
    parent closing is still a draft). admin sees every branch; branch is
    scoped to its own; staff — explicitly opted back into IsAuthenticated —
    only ever sees rows for the employee its own account is linked to."""

    serializer_class = WageEmployeeResultSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'patch', 'head', 'options']
    filterset_fields = ['closing', 'employee']

    def get_queryset(self):
        qs = WageEmployeeResult.objects.select_related('closing', 'employee').prefetch_related('daily_details')
        user = self.request.user
        if user.role == user.Role.ADMIN:
            return qs.filter(closing__branch__organization_id=user.organization_id)
        if user.role == user.Role.STAFF:
            if not user.staff_member_id:
                return qs.none()
            return qs.filter(employee_id=user.staff_member_id)
        return qs.filter(closing__branch_id=user.branch_id)

    def perform_update(self, serializer):
        instance = serializer.instance
        user = self.request.user
        if user.role == user.Role.STAFF:
            raise PermissionDenied('read-only for the staff role.')
        if instance.closing.status != WageMonthlyClosing.Status.DRAFT:
            raise ValidationError('wage-closing-not-draft')
        extra = {}
        if 'bonus_amount' in serializer.validated_data or 'bonus_note' in serializer.validated_data:
            extra['bonus_updated_by'] = user
            extra['bonus_updated_at'] = timezone.now()
        if 'monthly_transportation_override' in serializer.validated_data:
            extra['transportation_override_by'] = user
            extra['transportation_override_at'] = timezone.now()
        period_changed = bool(
            {'calculation_period_start', 'calculation_period_end'} & set(serializer.validated_data)
        )
        result = serializer.save(**extra)

        # bonus_amount / monthly_transportation_override directly affect
        # the displayed totals — recompute immediately rather than leaving
        # the payslip stale until the next full generate(). Clearing the
        # override (set to null) reverts to rule_transportation_amount,
        # the rule-derived default generate() always keeps up to date —
        # no regenerate needed either way.
        if 'bonus_amount' in serializer.validated_data or 'monthly_transportation_override' in serializer.validated_data:
            result.transportation_amount = (
                result.monthly_transportation_override
                if result.monthly_transportation_override is not None
                else result.rule_transportation_amount
            )
            result.estimated_total = result.base_amount + result.transportation_amount + result.bonus_amount
            result.save(update_fields=['transportation_amount', 'estimated_total'])

        # Scheme A: a special calculation window is never allowed to leave
        # stale money on screen or proceed to confirmation. Recompute the
        # whole draft closing immediately, including clearing an override.
        if period_changed:
            generate_wage_results(result.closing)
            result.closing.last_generated_at = timezone.now()
            result.closing.save(update_fields=['last_generated_at'])
            result.refresh_from_db()
            serializer.instance = result
