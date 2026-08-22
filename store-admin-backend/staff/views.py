from django.db import transaction
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from common.permissions import IsAdminRole

from .models import StaffMember, StaffTransfer
from .serializers import StaffMemberSerializer, StaffTransferSerializer


class StaffMemberViewSet(viewsets.ModelViewSet):
    """admin: every employee in its own Organization (never another
    customer's). branch: only employees at its own branch — new employees
    are auto-bound to the creating account's branch, and `branch` is never
    writable through this endpoint's normal update path for anyone, admin
    included; moving an employee to a different branch is a deliberate,
    separately-audited operation (see the staff-transfer endpoint), not a
    side effect of an ordinary edit. staff never reaches this endpoint at
    all (blocked by the project-wide DenyStaffRole default)."""

    serializer_class = StaffMemberSerializer
    filterset_fields = ['branch', 'status']

    def get_queryset(self):
        qs = StaffMember.objects.all()
        user = self.request.user
        if user.role == user.Role.ADMIN:
            return qs.filter(branch__organization_id=user.organization_id)
        return qs.filter(branch_id=user.branch_id)

    def perform_create(self, serializer):
        user = self.request.user
        if user.role == user.Role.ADMIN:
            branch = serializer.validated_data.get('branch')
            if not branch:
                raise PermissionDenied('branch is required for admin accounts.')
            if branch.organization_id != user.organization_id:
                raise PermissionDenied('cannot create an employee in another Organization\'s branch.')
            serializer.save()
        else:
            serializer.save(branch_id=user.branch_id)

    def perform_update(self, serializer):
        # `branch` is deliberately never accepted here, regardless of what
        # the request body contains — see the class docstring.
        serializer.save(branch=serializer.instance.branch)


class StaffTransferViewSet(viewsets.ModelViewSet):
    """The only way an employee's branch ever changes — admin-only (never
    branch, never staff), and only within the admin's own Organization.
    Read/create only (no PATCH/PUT/DELETE): once made, a transfer is a
    permanent audit record, never edited or un-done — an employee coming
    back to their original branch later gets a *new* transfer row, the old
    one is never touched."""

    serializer_class = StaffTransferSerializer
    permission_classes = [IsAdminRole]
    http_method_names = ['get', 'post', 'head', 'options']
    filterset_fields = ['employee', 'from_branch', 'to_branch']

    def get_queryset(self):
        return StaffTransfer.objects.filter(
            organization_id=self.request.user.organization_id,
        ).select_related('employee', 'from_branch', 'to_branch', 'changed_by')

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        employee = serializer.validated_data['employee']
        to_branch = serializer.validated_data['to_branch']
        effective_date = serializer.validated_data['effective_date']
        force = bool(request.data.get('force'))

        from_branch = employee.branch
        if from_branch.organization_id != user.organization_id or to_branch.organization_id != user.organization_id:
            raise PermissionDenied('cannot transfer an employee outside your Organization.')
        if to_branch.id == from_branch.id:
            raise ValidationError({'to_branch': ['employee is already at this branch.']})

        from scheduling.models import Shift
        future_shifts = Shift.objects.filter(
            employee=employee, branch=from_branch, work_date__gte=effective_date,
        ).order_by('work_date')
        if future_shifts.exists() and not force:
            return Response({
                'code': 'has-future-shifts-at-old-branch',
                'shifts': [
                    {'id': s.id, 'work_date': s.work_date.isoformat(), 'period_id': s.period_id}
                    for s in future_shifts
                ],
            }, status=400)

        with transaction.atomic():
            transfer = StaffTransfer.objects.create(
                employee=employee, organization=user.organization, from_branch=from_branch, to_branch=to_branch,
                effective_date=effective_date, reason=serializer.validated_data.get('reason', ''),
                changed_by=user,
            )
            employee.branch = to_branch
            employee.save(update_fields=['branch'])
            if hasattr(employee, 'user_account') and employee.user_account is not None:
                employee.user_account.branch = to_branch
                employee.user_account.save(update_fields=['branch'])

        return Response(self.get_serializer(transfer).data, status=201)
