from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.services import guard_account_deactivation
from common.features import FEATURE_REGISTRY, feature_state_for_org
from common.permissions import IsPlatformSuperuser

from .models import Organization, OrganizationFeature
from .overview import build_platform_overview


def _user_body(u):
    return {
        'id': u.id,
        'account': u.username,
        'displayName': u.first_name or u.username,
        'role': u.role,
        'branchId': u.branch_id,
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


class PlatformOverviewView(APIView):
    """GET /api/platform/overview/ — the super admin's cross-tenant data
    console: per-org counts + this-month money, plus platform totals."""

    permission_classes = [IsPlatformSuperuser]

    def get(self, request):
        return Response(build_platform_overview())


class PlatformOrganizationListView(APIView):
    """GET /api/platform/organizations/ — every tenant + its module
    entitlements. Platform super admin only."""

    permission_classes = [IsPlatformSuperuser]

    def get(self, request):
        orgs = Organization.objects.all().prefetch_related('branches')
        return Response([_org_body(o) for o in orgs])


class PlatformOrganizationFeaturesView(APIView):
    """PATCH /api/platform/organizations/<id>/features/ with a body like
    {"inventory": false, "products": true} — upserts the OrganizationFeature
    rows. Only keys in FEATURE_REGISTRY are accepted."""

    permission_classes = [IsPlatformSuperuser]

    def patch(self, request, org_id):
        org = Organization.objects.filter(id=org_id).first()
        if not org:
            raise NotFound('organization-not-found')

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


class PlatformOrganizationUsersView(APIView):
    """GET /api/platform/organizations/<id>/users/ — every account in the
    tenant, for the platform super admin's account overview."""

    permission_classes = [IsPlatformSuperuser]

    def get(self, request, org_id):
        if not Organization.objects.filter(id=org_id).exists():
            raise NotFound('organization-not-found')
        users = User.objects.filter(organization_id=org_id).select_related('branch').order_by('role', 'username')
        return Response([_user_body(u) for u in users])


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
