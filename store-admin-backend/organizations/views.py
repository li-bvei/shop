from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.services import guard_account_deactivation, guard_account_deletion
from branches.models import Branch
from common.features import FEATURE_REGISTRY, feature_state_for_org
from common.permissions import IsPlatformSuperuser
from staff.models import StaffMember

from .models import Organization, OrganizationFeature
from .overview import build_platform_overview
from .services import ProvisionError, create_branch_for_organization, provision_organization


def _user_body(u):
    return {
        'id': u.id,
        'account': u.username,
        'displayName': u.first_name or u.username,
        'role': u.role,
        'branchId': u.branch_id,
        'staffMemberId': u.staff_member_id,
        'isActive': u.is_active,
        'isSuperuser': u.is_superuser,
    }


def _org_body(org):
    return {
        'id': org.id,
        'code': org.code,
        'name_zh': org.name_zh,
        'name_ja': org.name_ja,
        'active': org.active,
        'branch_count': org.branches.count(),
        'features': feature_state_for_org(org.id),
    }


def _branch_body(b):
    return {
        'id': b.id,
        'code': b.code,
        'name_zh': b.name_zh,
        'name_ja': b.name_ja,
        'account_count': b.users.count(),
    }


def _get_org_or_404(org_id):
    org = Organization.objects.filter(id=org_id).first()
    if not org:
        raise NotFound('organization-not-found')
    return org


class PlatformOverviewView(APIView):
    """GET /api/platform/overview/ — the super admin's cross-tenant data
    console: per-org counts + this-month money, plus platform totals."""

    permission_classes = [IsPlatformSuperuser]

    def get(self, request):
        return Response(build_platform_overview())


class PlatformOrganizationListView(APIView):
    """GET /api/platform/organizations/ — every tenant + its module
    entitlements. POST creates a new tenant — the UI form for what
    `manage.py provision_organization` has always done from the shell,
    for onboarding a new chain without server access."""

    permission_classes = [IsPlatformSuperuser]

    def get(self, request):
        orgs = Organization.objects.all().prefetch_related('branches')
        return Response([_org_body(o) for o in orgs])

    def post(self, request):
        data = request.data
        for field in ('code', 'name_zh', 'name_ja'):
            if not data.get(field):
                raise ValidationError({field: ['This field is required.']})
        try:
            organization, branch, admin = provision_organization(
                code=data['code'], name_zh=data['name_zh'], name_ja=data['name_ja'],
                admin_account=data.get('admin_account') or None,
                admin_password=data.get('admin_password') or None,
                branch_code=data.get('branch_code') or None,
                branch_name_zh=data.get('branch_name_zh') or None,
                branch_name_ja=data.get('branch_name_ja') or None,
            )
        except ProvisionError as exc:
            raise ValidationError({'detail': [str(exc)]})
        return Response(_org_body(organization), status=201)


class PlatformOrganizationDetailView(APIView):
    """PATCH /api/platform/organizations/<id>/ — rename a tenant, or
    suspend/reactivate it (`active`). A suspended tenant's accounts are
    rejected at login and on every subsequent request — see
    common.authentication.OrganizationScopedJWTAuthentication."""

    permission_classes = [IsPlatformSuperuser]

    def patch(self, request, org_id):
        org = _get_org_or_404(org_id)
        data = request.data
        for field in ('name_zh', 'name_ja'):
            if field in data:
                setattr(org, field, (data[field] or '').strip())
        if 'active' in data:
            org.active = bool(data['active'])
        org.save(update_fields=['name_zh', 'name_ja', 'active', 'updated_at'])
        return Response(_org_body(org))


class PlatformOrganizationFeaturesView(APIView):
    """PATCH /api/platform/organizations/<id>/features/ with a body like
    {"inventory": false, "products": true} — upserts the OrganizationFeature
    rows. Only keys in FEATURE_REGISTRY are accepted."""

    permission_classes = [IsPlatformSuperuser]

    def patch(self, request, org_id):
        org = _get_org_or_404(org_id)

        updates = request.data if isinstance(request.data, dict) else {}
        unknown = [k for k in updates if k not in FEATURE_REGISTRY]
        if unknown:
            raise ValidationError({'features': [f'unknown-feature: {k}' for k in unknown]})

        for feature, enabled in updates.items():
            OrganizationFeature.objects.update_or_create(
                organization=org, feature=feature,
                defaults={'enabled': bool(enabled), 'updated_by': request.user},
            )
        return Response(_org_body(org))


class PlatformOrganizationBranchesView(APIView):
    """GET/POST /api/platform/organizations/<id>/branches/ — every branch
    in the tenant, and creating a new one. Same seeding a tenant's own
    admin gets from Settings (BranchViewSet.perform_create)."""

    permission_classes = [IsPlatformSuperuser]

    def get(self, request, org_id):
        org = _get_org_or_404(org_id)
        branches = org.branches.all().order_by('id')
        return Response([_branch_body(b) for b in branches])

    def post(self, request, org_id):
        org = _get_org_or_404(org_id)
        data = request.data
        for field in ('code', 'name_zh', 'name_ja'):
            if not data.get(field):
                raise ValidationError({field: ['This field is required.']})
        if Branch.objects.filter(organization=org, code=data['code']).exists():
            raise ValidationError({'code': ['branch-code-already-exists-in-organization']})
        branch = create_branch_for_organization(
            org, code=data['code'], name_zh=data['name_zh'], name_ja=data['name_ja'],
        )
        return Response(_branch_body(branch), status=201)


class PlatformBranchDetailView(APIView):
    """PATCH/DELETE /api/platform/branches/<id>/ — same rename/delete a
    tenant's own admin has in Settings, reachable by the platform super
    admin across any tenant."""

    permission_classes = [IsPlatformSuperuser]

    def _get_branch_or_404(self, branch_id):
        branch = Branch.objects.filter(id=branch_id).first()
        if not branch:
            raise NotFound('branch-not-found')
        return branch

    def patch(self, request, branch_id):
        branch = self._get_branch_or_404(branch_id)
        data = request.data
        for field in ('name_zh', 'name_ja'):
            if field in data:
                setattr(branch, field, (data[field] or '').strip())
        branch.save(update_fields=['name_zh', 'name_ja'])
        return Response(_branch_body(branch))

    def delete(self, request, branch_id):
        branch = self._get_branch_or_404(branch_id)
        if branch.users.exists():
            raise ValidationError({'detail': ['branch-has-accounts']})
        branch.delete()
        return Response(status=204)


class PlatformOrganizationUsersView(APIView):
    """GET /api/platform/organizations/<id>/users/ — every account in the
    tenant. POST creates one — same shape/rules as a tenant's own Settings
    account screen (accounts.serializers.UserSerializer.validate), just
    reachable for any organization instead of only the caller's own."""

    permission_classes = [IsPlatformSuperuser]

    def get(self, request, org_id):
        org = _get_org_or_404(org_id)
        users = User.objects.filter(organization=org, is_superuser=False).select_related('branch').order_by(
            'role', 'username',
        )
        return Response([_user_body(u) for u in users])

    def post(self, request, org_id):
        org = _get_org_or_404(org_id)
        data = request.data
        account = (data.get('account') or '').strip()
        password = data.get('password') or ''
        display_name = (data.get('display_name') or account).strip()
        role = data.get('role')
        if not account:
            raise ValidationError({'account': ['This field is required.']})
        if len(password) < 6:
            raise ValidationError({'password': ['Password must be at least 6 characters.']})
        if role not in (User.Role.ADMIN, User.Role.BRANCH, User.Role.STAFF):
            raise ValidationError({'role': ['Must be admin, branch or staff.']})
        if User.objects.filter(username=account).exists():
            raise ValidationError({'account': ['account-exists']})

        branch = None
        staff_member = None
        if role == User.Role.BRANCH:
            branch = Branch.objects.filter(id=data.get('branch_id'), organization=org).first()
            if not branch:
                raise ValidationError({'branch_id': ['This field is required.']})
        elif role == User.Role.STAFF:
            staff_member = StaffMember.objects.filter(id=data.get('staff_member_id'), branch__organization=org).first()
            if not staff_member:
                raise ValidationError({'staff_member_id': ['This field is required.']})
            if User.objects.filter(staff_member=staff_member).exists():
                raise ValidationError({'staff_member_id': ['employee-already-has-account']})
            branch = staff_member.branch

        user = User(
            username=account, first_name=display_name, role=role,
            organization=org, branch=branch, staff_member=staff_member,
        )
        user.set_password(password)
        user.save()
        return Response(_user_body(user), status=201)


class PlatformUserDetailView(APIView):
    """PATCH/DELETE /api/platform/users/<id>/ — edit display name / branch,
    or delete an account, across any tenant. Password changes go through
    the dedicated reset_password action below, same convention as the
    tenant-level account screen."""

    permission_classes = [IsPlatformSuperuser]

    def _get_user_or_404(self, user_id):
        user = User.objects.filter(id=user_id, is_superuser=False).first()
        if not user:
            raise NotFound('user-not-found')
        return user

    def patch(self, request, user_id):
        user = self._get_user_or_404(user_id)
        data = request.data
        if 'display_name' in data:
            user.first_name = (data['display_name'] or '').strip()
        if 'branch_id' in data and user.role == User.Role.BRANCH:
            branch = Branch.objects.filter(id=data['branch_id'], organization_id=user.organization_id).first()
            if not branch:
                raise ValidationError({'branch_id': ['branch-not-found']})
            user.branch = branch
        user.save()
        return Response(_user_body(user))

    def delete(self, request, user_id):
        user = self._get_user_or_404(user_id)
        if user == request.user:
            raise PermissionDenied('cannot delete the account you are currently logged in as.')
        guard_account_deletion(user, acting_user=request.user)
        user.delete()
        return Response(status=204)


class PlatformUserResetPasswordView(APIView):
    """POST /api/platform/users/<id>/reset_password/ {"password": "..."}"""

    permission_classes = [IsPlatformSuperuser]

    def post(self, request, user_id):
        user = User.objects.filter(id=user_id, is_superuser=False).first()
        if not user:
            raise NotFound('user-not-found')
        password = request.data.get('password', '')
        if len(password) < 6:
            raise ValidationError({'password': ['Password must be at least 6 characters.']})
        user.set_password(password)
        user.save()
        return Response({'status': 'ok'})


class PlatformUserSetActiveView(APIView):
    """POST /api/platform/users/<id>/set_active/ {"is_active": false} — the
    super admin can enable/disable any account across any tenant."""

    permission_classes = [IsPlatformSuperuser]

    def post(self, request, user_id):
        user = User.objects.filter(id=user_id).first()
        if not user:
            raise NotFound('user-not-found')
        is_active = bool(request.data.get('is_active'))
        guard_account_deactivation(user, is_active, acting_user=request.user)
        user.is_active = is_active
        user.save(update_fields=['is_active'])
        return Response(_user_body(user))
