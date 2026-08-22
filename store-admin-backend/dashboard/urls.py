from django.urls import path

from .views import DashboardSummaryView, MonthlyAnalysisView

urlpatterns = [
    path('dashboard/summary/', DashboardSummaryView.as_view(), name='dashboard-summary'),
    path('dashboard/monthly-analysis/', MonthlyAnalysisView.as_view(), name='dashboard-monthly-analysis'),
]
