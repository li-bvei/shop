from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ChangePasswordView, MeView, OrganizationView, PreferenceView, UserViewSet,
)

router = DefaultRouter()
router.register('users', UserViewSet, basename='user')

urlpatterns = [
    path('auth/me/', MeView.as_view(), name='auth-me'),
    path('auth/change-password/', ChangePasswordView.as_view(), name='auth-change-password'),
    path('auth/preference/', PreferenceView.as_view(), name='auth-preference'),
    path('organization/', OrganizationView.as_view(), name='organization'),
] + router.urls
