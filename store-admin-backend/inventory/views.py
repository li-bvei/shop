from decimal import Decimal, InvalidOperation

import django_filters
from django.db.models import F
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters as drf_filters, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from branches.models import Branch
from common.permissions import BranchScopedQuerysetMixin

from .models import Product, Stock, StockTransaction
from .serializers import ProductSerializer, StockSerializer, StockTransactionSerializer
from .services import adjust_stock


class ProductViewSet(viewsets.ModelViewSet):
    """Shared master data across all branches *within one Organization* —
    same scoping as Supplier. Stock levels live on Stock/StockTransaction,
    not here."""

    serializer_class = ProductSerializer
    filter_backends = [drf_filters.SearchFilter]
    search_fields = ['name', 'jan_code', 'category']

    def get_queryset(self):
        user = self.request.user
        return Product.objects.filter(organization_id=user.organization_id)

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)

    @action(detail=False, methods=['get'])
    def lookup(self, request):
        """Single-barcode lookup for the receiving/checkout scanner flow —
        scanners act as keyboard-wedge devices (they type the code +
        Enter), so the frontend just fires this on Enter with whatever
        landed in the JAN input."""
        jan = (request.query_params.get('jan') or '').strip()
        if not jan:
            return Response(None)
        product = self.get_queryset().filter(jan_code=jan).first()
        if not product:
            return Response(None)
        return Response(self.get_serializer(product).data)


class StockFilter(django_filters.FilterSet):
    low_stock = django_filters.BooleanFilter(method='filter_low_stock')

    class Meta:
        model = Stock
        fields = ['branch', 'product']

    def filter_low_stock(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            product__low_stock_threshold__isnull=False, quantity__lte=F('product__low_stock_threshold'),
        )


class StockViewSet(BranchScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """Current on-hand quantity per (branch, product). Read-only — the only
    way to change quantity is the `adjust` action below, which always goes
    through inventory.services.adjust_stock so the StockTransaction ledger
    can never drift out of sync with it."""

    queryset = Stock.objects.select_related('product', 'branch').all()
    serializer_class = StockSerializer
    filterset_class = StockFilter
    filter_backends = [DjangoFilterBackend]

    @action(detail=False, methods=['post'])
    def adjust(self, request):
        user = request.user
        branch_id = request.data.get('branch') or user.branch_id
        if not branch_id:
            raise ValidationError({'branch': ['Required for admin accounts.']})
        try:
            branch = Branch.objects.get(id=branch_id)
        except Branch.DoesNotExist:
            raise ValidationError({'branch': ['Not found.']})
        if branch.organization_id != user.organization_id:
            raise PermissionDenied()
        if user.role != user.Role.ADMIN and branch_id != user.branch_id:
            raise PermissionDenied()

        try:
            product = Product.objects.get(id=request.data.get('product'), organization_id=user.organization_id)
        except (Product.DoesNotExist, ValueError, TypeError):
            raise ValidationError({'product': ['Not found.']})

        transaction_type = request.data.get('transaction_type')
        if transaction_type not in StockTransaction.TransactionType.values:
            raise ValidationError({'transaction_type': ['Invalid.']})

        try:
            quantity = Decimal(str(request.data.get('quantity')))
        except (InvalidOperation, TypeError):
            raise ValidationError({'quantity': ['Invalid.']})

        stock, _record = adjust_stock(
            branch=branch, product=product, transaction_type=transaction_type,
            quantity=quantity, note=request.data.get('note', ''), operator=user,
        )
        return Response(StockSerializer(stock).data, status=201)


class StockTransactionViewSet(BranchScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = StockTransaction.objects.select_related('product', 'branch', 'operator').all()
    serializer_class = StockTransactionSerializer
    filterset_fields = ['branch', 'product', 'transaction_type']
    filter_backends = [DjangoFilterBackend]
