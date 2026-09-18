from django.urls import path

from .views import DashboardSummaryView, MonthlyAnalysisView, YearlyAnalysisView

urlpatterns = [
    path('dashboard/summary/', DashboardSummaryView.as_view(), name='dashboard-summary'),
    path('dashboard/monthly-analysis/', MonthlyAnalysisView.as_view(), name='dashboard-monthly-analysis'),
    path('dashboard/yearly-analysis/', YearlyAnalysisView.as_view(), name='dashboard-yearly-analysis'),
]
