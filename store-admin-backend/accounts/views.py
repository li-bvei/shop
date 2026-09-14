from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from common.permissions import IsAdminRole

from .models import User, UserPreference
from .serializers import (
    MeSerializer, OrganizationScopedTokenObtainPairSerializer, UserPreferenceSerializer, UserSerializer,
)
from .services import guard_account_deactivation, guard_account_deletion


class OrganizationScopedTokenObtainPairView(TokenObtainPairView):
    serializer_class = OrganizationScopedTokenObtainPairSerializer


class MeView(RetrieveAPIView):
    # Every role, including staff, needs this right after login to learn
    # who it is — explicitly opts out of the project-wide DenyStaffRole
    # default (see REST_FRAMEWORK.DEFAULT_PERMISSION_CLASSES).
    permission_classes = [IsAuthenticated]
    serializer_class = MeSerializer

    def get_object(self):
        return self.request.user


class OrganizationView(APIView):
    """The caller's own tenant. Every role may read it (the customer-facing
    loyalty pages need the brand logo); only an admin may change the
    display name / logo."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(_org_body(request.user.organization))

    def patch(self, request):
        if request.user.role != request.user.Role.ADMIN:
            raise PermissionDenied('admin-only')
        org = request.user.organization
        update_fields = ['updated_at']
        for field in ('name_zh', 'name_ja', 'logo_url'):
            if field in request.data:
                setattr(org, field, (request.data[field] or '').strip())
                update_fields.append(field)
        if 'logo_url' in request.data:
            org.logo_url = _clean_logo(org.logo_url)
        if 'report_unlock_password' in request.data:
            password = (request.data['report_unlock_password'] or '').strip()
            if password and len(password) < 4:
                raise ValidationError({'report_unlock_password': ['too-short']})
            # Empty string explicitly clears it — that's how an admin turns
            # the lock feature back off for the org (see report_lock.py).
            org.report_unlock_password_hash = make_password(password) if password else ''
            update_fields.append('report_unlock_password_hash')
        try:
            org.full_clean(exclude=['code'])
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict)
        org.save(update_fields=update_fields)
        return Response(_org_body(org))


# A logo is either a link the chain hosts, or a small inline image the admin
# uploaded in Settings (the frontend resizes it to ≤256px before encoding).
_LOGO_MAX_LEN = 500_000  # ~365KB of image once base64 is decoded


def _clean_logo(value):
    if not value:
        return ''
    if value.startswith(('http://', 'https://')):
        return value
    if value.startswith('data:image/'):
        if len(value) > _LOGO_MAX_LEN:
            raise ValidationError({'logo_url': ['image-too-large']})
        return value
    raise ValidationError({'logo_url': ['must-be-an-image-or-https-url']})


def _org_body(org):
    return {
        'code': org.code,
        'name_zh': org.name_zh,
        'name_ja': org.name_ja,
        'logo_url': org.logo_url,
        'report_unlock_password_set': bool(org.report_unlock_password_hash),
    }


class PreferenceView(APIView):
    """Self-service UI preferences (locale/theme) — every account reads and
    writes only its own row, created lazily on first access so there's no
    seed step every account needs to go through first."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        preference, _ = UserPreference.objects.get_or_create(user=request.user)
        return Response(UserPreferenceSerializer(preference).data)

    def patch(self, request):
        preference, _ = UserPreference.objects.get_or_create(user=request.user)
        serializer = UserPreferenceSerializer(preference, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class UserViewSet(viewsets.ModelViewSet):
    """Account management — admin only, and scoped to the admin's own
    Organization: an admin can only ever see, create, edit, reset the
    password of, or delete accounts belonging to its own Organization,
    never another customer's. Mirrors the frontend's 账号管理, plus a
    reset_password action for forcing a new password onto any account
    without knowing the old one."""

    serializer_class = UserSerializer
    permission_classes = [IsAdminRole]

    def get_queryset(self):
        # is_superuser=False: a platform superuser account can belong to an
        # Organization (see organizations.views.PlatformOrganizationUsersView)
        # without being manageable by that org's own admin — it must never
        # show up in, or be editable from, a regular org's account list.
        return User.objects.filter(organization_id=self.request.user.organization_id, is_superuser=False)

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)

    def perform_destroy(self, instance):
        guard_account_deletion(instance, acting_user=self.request.user)
        instance.delete()

    @action(detail=True, methods=['post'])
    def reset_password(self, request, pk=None):
        user = self.get_object()
        new_password = request.data.get('password', '')
        if len(new_password) < 6:
            raise ValidationError({'password': ['Password must be at least 6 characters.']})
        user.set_password(new_password)
        user.save()
        return Response({'status': 'ok'})

    @action(detail=True, methods=['post'])
    def set_active(self, request, pk=None):
        """Enable / disable an account. A disabled account can't log in and
        its live tokens stop working right away."""
        user = self.get_object()
        is_active = bool(request.data.get('is_active'))
        guard_account_deactivation(user, is_active, acting_user=request.user)
        user.is_active = is_active
        user.save(update_fields=['is_active'])
        return Response(UserSerializer(user, context={'request': request}).data)


class ChangePasswordView(APIView):
    """Self-service — any authenticated account changes its own password,
    old password required."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        old_password = request.data.get('old_password', '')
        new_password = request.data.get('new_password', '')
        user = request.user
        if not user.check_password(old_password):
            raise ValidationError({'old_password': ['invalid-old-password']})
        if len(new_password) < 6:
            raise ValidationError({'new_password': ['Password must be at least 6 characters.']})
        user.set_password(new_password)
        user.save()
        return Response({'status': 'ok'})
