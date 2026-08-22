from django.contrib import admin

from .models import PaymentMethodDef


@admin.register(PaymentMethodDef)
class PaymentMethodDefAdmin(admin.ModelAdmin):
    list_display = ['code', 'custom_name', 'i18n_key', 'sort_order']
