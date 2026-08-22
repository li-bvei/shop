from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (
        ('Store role', {'fields': ('role', 'branch')}),
    )
    list_display = ['username', 'role', 'branch', 'is_staff']
    list_filter = ['role', 'branch', 'is_staff']
