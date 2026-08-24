from django.contrib import admin

from .models import Product, Stock, StockTransaction


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'jan_code', 'category', 'unit', 'selling_price', 'status']
    search_fields = ['name', 'jan_code']
    list_filter = ['status', 'category']


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ['branch', 'product', 'quantity', 'updated_at']
    list_filter = ['branch']


@admin.register(StockTransaction)
class StockTransactionAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'branch', 'product', 'transaction_type', 'quantity', 'operator']
    list_filter = ['branch', 'transaction_type']
