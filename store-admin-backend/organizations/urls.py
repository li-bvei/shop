from django.urls import path

from .views import (
    PlatformBranchDetailView, PlatformOrganizationBranchesView, PlatformOrganizationDetailView,
    PlatformOrganizationFeaturesView, PlatformOrganizationListView, PlatformOrganizationUsersView,
    PlatformOverviewView, PlatformUserDetailView, PlatformUserResetPasswordView, PlatformUserSetActiveView,
)

urlpatterns = [
    path('platform/overview/', PlatformOverviewView.as_view(), name='platform-overview'),
    path('platform/organizations/', PlatformOrganizationListView.as_view(), name='platform-organizations'),
    path(
        'platform/organizations/<int:org_id>/',
        PlatformOrganizationDetailView.as_view(),
        name='platform-organization-detail',
    ),
    path(
        'platform/organizations/<int:org_id>/features/',
        PlatformOrganizationFeaturesView.as_view(),
        name='platform-organization-features',
    ),
    path(
        'platform/organizations/<int:org_id>/branches/',
        PlatformOrganizationBranchesView.as_view(),
        name='platform-organization-branches',
    ),
    path(
        'platform/organizations/<int:org_id>/users/',
        PlatformOrganizationUsersView.as_view(),
        name='platform-organization-users',
    ),
    path('platform/branches/<str:branch_id>/', PlatformBranchDetailView.as_view(), name='platform-branch-detail'),
    path('platform/users/<int:user_id>/', PlatformUserDetailView.as_view(), name='platform-user-detail'),
    path(
        'platform/users/<int:user_id>/reset_password/',
        PlatformUserResetPasswordView.as_view(),
        name='platform-user-reset-password',
    ),
    path(
        'platform/users/<int:user_id>/set_active/',
        PlatformUserSetActiveView.as_view(),
        name='platform-user-set-active',
    ),
]
