from rest_framework.routers import DefaultRouter

from .views import StaffMemberViewSet, StaffTransferViewSet

router = DefaultRouter()
router.register('staff', StaffMemberViewSet, basename='staff')
router.register('staff-transfers', StaffTransferViewSet, basename='staff-transfer')

urlpatterns = router.urls
