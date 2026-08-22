from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError

from paymentmethods.models import seed_default_payment_methods
from scheduling.services import seed_default_schedule_setting

from .models import Branch
from .serializers import BranchSerializer


class BranchViewSet(viewsets.ModelViewSet):
    """admin manages every branch; branch accounts may only read their own
    branch and can never create/update/delete a branch — hiding the
    add/edit/delete buttons in the frontend is UX only, this is the actual
    enforcement. staff never reaches this endpoint at all — no
    permission_classes override here, so it inherits the project-wide
    IsAuthenticated + DenyStaffRole default; do not add IsAuthenticated
    explicitly, that would opt back out of the staff block."""

    serializer_class = BranchSerializer

    def get_queryset(self):
        qs = Branch.objects.all()
        user = self.request.user
        if user.role == user.Role.ADMIN:
            return qs.filter(organization_id=user.organization_id)
        return qs.filter(id=user.branch_id)

    def _deny_non_admin_write(self):
        if self.request.user.role != self.request.user.Role.ADMIN:
            raise PermissionDenied('only admin accounts can manage branches.')

    def perform_create(self, serializer):
        self._deny_non_admin_write()
        branch = serializer.save(
            organization=self.request.user.organization,
            code=serializer.validated_data.get('code') or serializer.validated_data['id'],
        )
        seed_default_payment_methods(branch)
        seed_default_schedule_setting(branch)

    def perform_update(self, serializer):
        self._deny_non_admin_write()
        serializer.save()

    def perform_destroy(self, instance):
        self._deny_non_admin_write()
        if instance.users.exists():
            raise ValidationError('branch-has-accounts')
        instance.delete()
