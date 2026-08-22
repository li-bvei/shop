from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission


class BranchScopedQuerysetMixin:
    """Restrict a viewset to the requesting user's Organization, and
    further to its own branch unless it's an admin: admins see/write every
    branch *in their own Organization*, branch accounts only ever see/write
    their own branch. `branch_field` supports records where the branch
    lives behind a relation (e.g. 'branch_id')."""

    branch_field = 'branch_id'

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        relation_name = self.branch_field.removesuffix('_id')
        if user.role == user.Role.ADMIN:
            return qs.filter(**{f'{relation_name}__organization_id': user.organization_id})
        return qs.filter(**{self.branch_field: user.branch_id})

    def perform_create(self, serializer):
        user = self.request.user
        if user.role == user.Role.ADMIN:
            # validated_data is keyed by the serializer field name ('branch'),
            # not the '_id' suffixed ORM lookup used for filtering/saving below.
            relation_name = self.branch_field.removesuffix('_id')
            branch = serializer.validated_data.get(relation_name)
            if not branch:
                raise ValidationError({relation_name: ['This field is required for admin accounts.']})
            if branch.organization_id != user.organization_id:
                raise ValidationError({relation_name: ['branch-outside-organization']})
            serializer.save()
        else:
            serializer.save(**{self.branch_field: user.branch_id})

    def perform_update(self, serializer):
        """A normal PATCH can never move a branch-scoped business row.

        Cross-branch moves, where supported, must use a dedicated audited
        action (for example StaffTransfer).  Keeping this invariant here
        also closes the common "retrieve in tenant A, PATCH branch=B" hole.
        """
        relation_name = self.branch_field.removesuffix('_id')
        serializer.save(**{relation_name: getattr(serializer.instance, relation_name)})


class IsAdminRole(BasePermission):
    """Restricts a view to accounts with role='admin' — used for account/
    branch management endpoints that only the chain admin should reach."""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role == user.Role.ADMIN)


class DenyStaffRole(BasePermission):
    """Project-wide default (see REST_FRAMEWORK.DEFAULT_PERMISSION_CLASSES):
    blocks the staff role from every endpoint except the explicit
    self-service allowlist — auth/me, change-password, preference, and the
    scheduling/actual-work/wage self-service read views — which each
    override `permission_classes` back to plain IsAuthenticated to opt in.
    Staff must never reach dashboards, daily reports, purchasing, supplier,
    payment-method, staff-list, or account-management endpoints; hiding
    those in the frontend nav is not itself a permission control."""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role != user.Role.STAFF)
