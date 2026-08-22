from rest_framework.routers import DefaultRouter

from .views import (
    ActualWorkRecordViewSet, AvailabilityRequestViewSet, BranchScheduleSettingViewSet,
    SchedulePeriodViewSet, ShiftViewSet,
)

router = DefaultRouter()
router.register('branch-schedule-settings', BranchScheduleSettingViewSet, basename='branch-schedule-setting')
router.register('schedule-periods', SchedulePeriodViewSet, basename='schedule-period')
router.register('availability-requests', AvailabilityRequestViewSet, basename='availability-request')
router.register('shifts', ShiftViewSet, basename='shift')
router.register('actual-work-records', ActualWorkRecordViewSet, basename='actual-work-record')

urlpatterns = router.urls
