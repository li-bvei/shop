from rest_framework.routers import DefaultRouter

from .views import (
    ActualWorkRecordViewSet, AttendanceChangeLogViewSet, AttendanceCorrectionRequestViewSet,
    AttendancePunchViewSet, AvailabilityRequestViewSet, BranchScheduleSettingViewSet,
    SchedulePeriodViewSet, ShiftViewSet,
)

router = DefaultRouter()
router.register('branch-schedule-settings', BranchScheduleSettingViewSet, basename='branch-schedule-setting')
router.register('schedule-periods', SchedulePeriodViewSet, basename='schedule-period')
router.register('availability-requests', AvailabilityRequestViewSet, basename='availability-request')
router.register('shifts', ShiftViewSet, basename='shift')
router.register('actual-work-records', ActualWorkRecordViewSet, basename='actual-work-record')
router.register('attendance-punches', AttendancePunchViewSet, basename='attendance-punch')
router.register('attendance-corrections', AttendanceCorrectionRequestViewSet, basename='attendance-correction')
router.register('attendance-change-logs', AttendanceChangeLogViewSet, basename='attendance-change-log')

urlpatterns = router.urls
