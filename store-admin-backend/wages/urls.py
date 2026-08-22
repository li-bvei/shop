from rest_framework.routers import DefaultRouter

from .views import WageEmployeeResultViewSet, WageMonthlyClosingViewSet, WageRuleViewSet

router = DefaultRouter()
router.register('wage-rules', WageRuleViewSet, basename='wage-rule')
router.register('wage-monthly-closings', WageMonthlyClosingViewSet, basename='wage-monthly-closing')
router.register('wage-employee-results', WageEmployeeResultViewSet, basename='wage-employee-result')

urlpatterns = router.urls
