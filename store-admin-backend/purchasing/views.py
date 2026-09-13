import django_filters
from django.db.models import Count, Sum
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters as drf_filters, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from common.permissions import BranchScopedQuerysetMixin

from .models import PurchaseRecord, Supplier
from .serializers import PurchaseRecordSerializer, SupplierSerializer
from .services import compute_price_comparisons, compute_prior_purchase_deltas
from .utils import normalize_item_name


class SupplierViewSet(viewsets.ModelViewSet):
    """Shared master data across all branches *within one Organization* —
    never across Organizations."""

    serializer_class = SupplierSerializer

    def get_queryset(self):
        # Most-used suppliers first (by purchase record count) instead of
        # kana/alphabetical order, so the entry-row dropdown surfaces the
        # suppliers staff actually order from most often at the top.
        user = self.request.user
        return Supplier.objects.filter(organization_id=user.organization_id).annotate(
            purchase_count=Count('purchase_records'),
        ).order_by('-purchase_count', 'name')

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)


class PurchasePagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


class PurchaseRecordFilter(django_filters.FilterSet):
    month = django_filters.CharFilter(method='filter_month')
    date_from = django_filters.DateFilter(field_name='date', lookup_expr='gte')
    date_to = django_filters.DateFilter(field_name='date', lookup_expr='lte')
    item_name = django_filters.CharFilter(method='filter_item_name')

    class Meta:
        model = PurchaseRecord
        fields = ['branch', 'supplier']

    def filter_month(self, queryset, name, value):
        try:
            year_str, month_str = value.split('-')
            year, month = int(year_str), int(month_str)
        except (ValueError, AttributeError):
            return queryset.none()
        return queryset.filter(date__year=year, date__month=month)

    def filter_item_name(self, queryset, name, value):
        return queryset.filter(item_name_normalized__icontains=normalize_item_name(value))


class PurchaseRecordViewSet(BranchScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = PurchaseRecord.objects.select_related('supplier', 'branch').all()
    serializer_class = PurchaseRecordSerializer
    filterset_class = PurchaseRecordFilter
    filter_backends = [DjangoFilterBackend, drf_filters.OrderingFilter]
    ordering_fields = ['date', 'unit_price', 'amount', 'item_name']
    ordering = ['-date', '-id']
    pagination_class = PurchasePagination

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        # OrderingFilter fully replaces the queryset's ordering with whatever
        # single field the frontend requested (e.g. just 'date') the moment an
        # `ordering` query param is present — it doesn't fall back to this
        # viewset's own `ordering = ['-date', '-id']` default for the tiebreak
        # anymore. Without `-id` here, several rows entered on the same date
        # come back in whatever order the DB happens to return them, not
        # newest-entered-first. Appending it is always safe (redundant, never
        # wrong) even when the requested field already disambiguates ties.
        order_by = list(queryset.query.order_by)
        if 'id' not in order_by and '-id' not in order_by:
            queryset = queryset.order_by(*order_by, '-id')
        price_change = self.request.query_params.get('price_change')
        if price_change and self.action == 'list':
            if price_change not in ('up', 'down'):
                raise ValidationError({'price_change': ["Must be 'up' or 'down'."]})
            if not self.request.query_params.get('month'):
                # Comparing price direction over an unbounded date range would
                # require pulling every matching record into Python just to
                # group them — cheap for one month, not for the whole table.
                raise ValidationError({'price_change': ['Requires the month filter to also be set.']})
            comparisons = compute_price_comparisons(queryset)
            matching_ids = [rid for rid, v in comparisons.items() if v['direction'] == price_change]
            queryset = queryset.filter(id__in=matching_ids)
        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        target = page if page is not None else queryset
        context = {
            **self.get_serializer_context(),
            'price_comparisons': compute_price_comparisons(target),
            'prior_purchase_deltas': compute_prior_purchase_deltas(target),
        }
        serializer = self.get_serializer(target, many=True, context=context)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def month_total(self, request):
        """Sum of `amount` over whatever filters are in effect, computed
        DB-side. Exists so the frontend's month-total tile no longer has to
        page through every matching record just to add them up client-side
        — that extra unbounded fetch (on top of the already-paginated list
        request) was the main cost behind the multi-second filter/page
        delay reported against this view."""
        total = self.filter_queryset(self.get_queryset()).aggregate(total=Sum('amount'))['total']
        return Response({'total': total or 0})

    @action(detail=False, methods=['post'])
    def bulk_replace(self, request):
        """Find-and-replace one specific wrong value across every matching
        record — e.g. a whole delivery was logged under the wrong date, or
        under the wrong supplier. Narrow the search with the same query
        params the list view accepts (branch/supplier/month/item_name),
        then supply the exact `field` + `old_value` to find and the
        `new_value` to replace it with. Always previews the match count
        and a short sample first; only writes when `confirm: true` is
        also sent, so a mistyped old_value can't silently rewrite more
        rows than intended.

        Only `date` and `supplier` are replaceable — item_name/quantity/
        unit_price are typed per row on purpose (batch-editing those would
        mean overwriting a mix of different real transactions, not fixing
        one repeated mistake)."""
        field = request.data.get('field')
        if field not in ('date', 'supplier'):
            raise ValidationError({'field': ["Must be 'date' or 'supplier'."]})

        old_value = request.data.get('old_value')
        new_value = request.data.get('new_value')
        if not old_value or not new_value:
            raise ValidationError({'old_value': ['old_value and new_value are both required.']})

        lookup_field = 'supplier_id' if field == 'supplier' else field
        if field == 'supplier':
            new_supplier = Supplier.objects.filter(
                id=new_value, organization_id=request.user.organization_id,
            ).first()
            if not new_supplier:
                raise ValidationError({'new_value': ['supplier-not-found']})

        queryset = self.filter_queryset(self.get_queryset())
        try:
            queryset = queryset.filter(**{lookup_field: old_value})
        except (ValueError, TypeError) as exc:
            raise ValidationError({'old_value': [str(exc)]})

        count = queryset.count()
        if not request.data.get('confirm'):
            preview = list(
                queryset.select_related('supplier').order_by('-date', '-id')[:20].values(
                    'id', 'date', 'branch_id', 'supplier_id', 'supplier__name', 'item_name', 'quantity', 'unit_price',
                ),
            )
            return Response({'matchedCount': count, 'preview': preview})

        if count:
            queryset.update(**{lookup_field: new_value})
        return Response({'replacedCount': count})

    @action(detail=False, methods=['get'])
    def suggestions(self, request):
        """Item-name autocomplete for the entry row, ranked by the same
        frequency+recency score the frontend mock used, scoped to one
        supplier so unit prices stay comparable.

        Grouped in Python from one flat, already-recency-ordered fetch
        rather than a GROUP BY with a correlated per-group subquery — the
        latter took 2+ seconds against a supplier with ~2,000 records
        (no index makes a per-distinct-item-name subquery cheap at that
        scale). One bounded query is fast regardless of table growth."""
        supplier_id = request.query_params.get('supplier')
        keyword = request.query_params.get('q', '')
        if not supplier_id:
            return Response([])

        qs = self.get_queryset().filter(supplier_id=supplier_id)
        if keyword:
            qs = qs.filter(item_name__icontains=keyword)

        # Ranking only ever rewards recent activity (score caps the recency
        # bonus at 60 days back), so capping the scan at the most recent
        # 500 records per supplier changes nothing about which items rank
        # highest — it only bounds worst-case cost as the table grows.
        rows = qs.order_by('-date', '-id').values_list('item_name', 'date', 'unit_price')[:500]

        today = timezone.localdate()
        groups: dict[str, dict] = {}
        for item_name, date, unit_price in rows:
            group = groups.setdefault(item_name, {'use_count': 0, 'latest_date': date, 'latest_unit_price': unit_price})
            group['use_count'] += 1

        results = []
        for item_name, group in groups.items():
            days_since_latest = (today - group['latest_date']).days
            score = group['use_count'] * 20 + max(0, 60 - days_since_latest)
            results.append({
                'itemName': item_name,
                'lastUnitPrice': group['latest_unit_price'] or 0,
                'useCount': group['use_count'],
                '_score': score,
            })

        results.sort(key=lambda r: r['_score'], reverse=True)
        for r in results:
            r.pop('_score')
        return Response(results[:10])

    @action(detail=False, methods=['get'])
    def price_history(self, request):
        """Chronological unit-price history for one (branch, supplier, item)
        — kept branch-specific throughout, same as the month-over-month
        comparison, since different branches may have different negotiated
        prices with the same supplier."""
        branch_id = request.query_params.get('branch')
        supplier_id = request.query_params.get('supplier')
        item_name = request.query_params.get('item_name')
        if not branch_id or not supplier_id or not item_name:
            raise ValidationError({'branch': ['branch, supplier and item_name are all required.']})

        qs = self.get_queryset().filter(
            branch_id=branch_id, supplier_id=supplier_id,
            item_name_normalized=normalize_item_name(item_name),
        ).order_by('-date', '-id')[:100]

        return Response([
            {
                'id': r.id, 'date': r.date, 'itemName': r.item_name,
                'quantity': r.quantity, 'unitPrice': r.unit_price, 'amount': r.amount,
            }
            for r in qs
        ])

    @action(detail=False, methods=['get'])
    def supplier_comparison(self, request):
        """Cross-supplier price comparison for one item at one branch — the
        one place this feature deliberately *does* mix suppliers, since the
        entire point is letting the user pick the cheaper one."""
        branch_id = request.query_params.get('branch')
        item_name = request.query_params.get('item_name')
        if not branch_id or not item_name:
            raise ValidationError({'branch': ['branch and item_name are both required.']})

        qs = self.get_queryset().filter(
            branch_id=branch_id, item_name_normalized=normalize_item_name(item_name),
        ).select_related('supplier').order_by('-date', '-id')

        by_supplier = {}
        for r in qs:
            entry = by_supplier.setdefault(r.supplier_id, {
                'supplierId': r.supplier_id, 'supplierName': r.supplier.name,
                'latestUnitPrice': None, 'latestDate': None, 'recordCount': 0, 'prices': [],
            })
            entry['recordCount'] += 1
            if entry['latestDate'] is None:
                entry['latestUnitPrice'] = r.unit_price
                entry['latestDate'] = r.date
            entry['prices'].append(r.unit_price)

        results = []
        for entry in by_supplier.values():
            prices = entry.pop('prices')
            entry['avgUnitPrice'] = sum(prices) / len(prices) if prices else None
            results.append(entry)
        results.sort(key=lambda e: (e['latestUnitPrice'] is None, e['latestUnitPrice'] or 0))
        return Response(results)
