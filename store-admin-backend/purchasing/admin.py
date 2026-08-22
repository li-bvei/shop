from django.contrib import admin

from .models import PurchaseRecord, Supplier


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'contact', 'phone', 'payable_override']
    search_fields = ['name']


@admin.register(PurchaseRecord)
class PurchaseRecordAdmin(admin.ModelAdmin):
    list_display = ['date', 'branch', 'supplier', 'item_name', 'quantity', 'unit_price', 'amount']
    list_filter = ['branch', 'supplier']
