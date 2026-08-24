from rest_framework import serializers

from .models import Product, Stock, StockTransaction


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = [
            'id', 'jan_code', 'name', 'category', 'unit',
            'selling_price', 'cost_price', 'low_stock_threshold', 'status', 'note',
        ]

    def validate_jan_code(self, value):
        value = value.strip()
        if not value:
            return value
        # The model's UniqueConstraint has a `condition=`, which MySQL
        # (unlike Postgres/SQLite) silently refuses to create — see the
        # W036 system-check warning. Enforced here instead so production
        # (MySQL) and dev/test (SQLite) behave identically.
        request = self.context.get('request')
        organization_id = request.user.organization_id if request else None
        qs = Product.objects.filter(organization_id=organization_id, jan_code=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('duplicate-jan-code-in-organization')
        return value


class StockSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    jan_code = serializers.CharField(source='product.jan_code', read_only=True)
    category = serializers.CharField(source='product.category', read_only=True)
    unit = serializers.CharField(source='product.unit', read_only=True)
    low_stock_threshold = serializers.DecimalField(
        source='product.low_stock_threshold', max_digits=10, decimal_places=2, read_only=True,
    )
    is_low_stock = serializers.SerializerMethodField()

    class Meta:
        model = Stock
        fields = [
            'id', 'branch', 'product', 'product_name', 'jan_code', 'category', 'unit',
            'quantity', 'low_stock_threshold', 'is_low_stock', 'updated_at',
        ]

    def get_is_low_stock(self, obj):
        threshold = obj.product.low_stock_threshold
        return threshold is not None and obj.quantity <= threshold


class StockTransactionSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    operator_name = serializers.SerializerMethodField()

    class Meta:
        model = StockTransaction
        fields = [
            'id', 'branch', 'product', 'product_name', 'transaction_type',
            'quantity', 'note', 'operator_name', 'created_at',
        ]

    def get_operator_name(self, obj):
        return obj.operator.first_name or obj.operator.username if obj.operator else ''
