from django.urls import path

from .views import (
    PlatformOrganizationFeaturesView, PlatformOrganizationListView, PlatformOrganizationUsersView,
    PlatformOverviewView, PlatformUserSetActiveView,
)

urlpatterns = [
    path('platform/overview/', PlatformOverviewView.as_view(), name='platform-overview'),
    path('platform/organizations/', PlatformOrganizationListView.as_view(), name='platform-organizations'),
    path(
        'platform/organizations/<int:org_id>/features/',
        PlatformOrganizationFeaturesView.as_view(),
        name='platform-organization-features',
    ),
    path(
        'platform/organizations/<int:org_id>/users/',
        PlatformOrganizationUsersView.as_view(),
        name='platform-organization-users',
    ),
    path(
        'platform/users/<int:user_id>/set_active/',
        PlatformUserSetActiveView.as_view(),
        name='platform-user-set-active',
    ),
]
