from django.contrib import admin

from .models import Organization, OrganizationFeature


class OrganizationFeatureInline(admin.TabularInline):
    model = OrganizationFeature
    extra = 0
    fields = ['feature', 'enabled', 'note']


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ['code', 'name_zh', 'name_ja', 'active']
    fields = ['code', 'name_zh', 'name_ja', 'logo_url', 'active']
    inlines = [OrganizationFeatureInline]


@admin.register(OrganizationFeature)
class OrganizationFeatureAdmin(admin.ModelAdmin):
    list_display = ['organization', 'feature', 'enabled', 'updated_at']
    list_filter = ['enabled', 'feature']
    list_editable = ['enabled']
