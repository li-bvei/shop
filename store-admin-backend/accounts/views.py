from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common.permissions import IsAdminRole

from .models import User, UserPreference
from .serializers import MeSerializer, UserPreferenceSerializer, UserSerializer


class MeView(RetrieveAPIView):
    # Every role, including staff, needs this right after login to learn
    # who it is — explicitly opts out of the project-wide DenyStaffRole
    # default (see REST_FRAMEWORK.DEFAULT_PERMISSION_CLASSES).
    permission_classes = [IsAuthenticated]
    serializer_class = MeSerializer

    def get_object(self):
        return self.request.user


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
        return User.objects.filter(organization_id=self.request.user.organization_id)

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)

    def perform_destroy(self, instance):
        if instance == self.request.user:
            raise ValidationError('cannot delete the account you are currently logged in as.')
        if instance.role == User.Role.ADMIN and User.objects.filter(
            role=User.Role.ADMIN, organization_id=self.request.user.organization_id,
        ).count() <= 1:
            raise ValidationError('at least one admin account must remain.')
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
