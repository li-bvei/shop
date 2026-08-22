from rest_framework.routers import DefaultRouter

from .views import DailyReportHistoryViewSet, DailyReportViewSet

router = DefaultRouter()
router.register('daily-reports', DailyReportViewSet, basename='daily-report')
router.register('daily-report-history', DailyReportHistoryViewSet, basename='daily-report-history')

urlpatterns = router.urls
