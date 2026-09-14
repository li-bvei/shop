from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CashRegisterDefaultsView, DailyReportHistoryViewSet, DailyReportViewSet, ReportUnlockView

router = DefaultRouter()
router.register('daily-reports', DailyReportViewSet, basename='daily-report')
router.register('daily-report-history', DailyReportHistoryViewSet, basename='daily-report-history')

urlpatterns = router.urls + [
    path('cash-register-defaults/', CashRegisterDefaultsView.as_view(), name='cash-register-defaults'),
    path('daily-reports-unlock/', ReportUnlockView.as_view(), name='daily-reports-unlock'),
]
