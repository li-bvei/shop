from django.contrib import admin

from .models import DailyReport, DailyReportHistory


@admin.register(DailyReport)
class DailyReportAdmin(admin.ModelAdmin):
    list_display = ['branch', 'date', 'person_in_charge', 'total_revenue', 'updated_at']
    list_filter = ['branch']


@admin.register(DailyReportHistory)
class DailyReportHistoryAdmin(admin.ModelAdmin):
    list_display = ['branch', 'date', 'saved_at', 'edited_by_name', 'total_revenue', 'cash_remaining']
    list_filter = ['branch']
