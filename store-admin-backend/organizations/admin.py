from django.contrib import admin

from .models import Organization


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ['code', 'name_zh', 'name_ja', 'active']
    fields = ['code', 'name_zh', 'name_ja', 'logo_url', 'active']
