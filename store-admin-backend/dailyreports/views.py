from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from common.permissions import BranchScopedQuerysetMixin

from .models import DailyReport, DailyReportHistory
from .serializers import DailyReportHistorySerializer, DailyReportSerializer


class DailyReportViewSet(BranchScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = DailyReport.objects.all()
    serializer_class = DailyReportSerializer
    filterset_fields = ['branch', 'date']

    @action(detail=False, methods=['get'])
    def expense_suggestions(self, request):
        """Item-name autocomplete for the 报销明细 rows, ranked by the same
        frequency+recency score used elsewhere, built from every expense
        line ever recorded for the branch (live reports + full history)."""
        branch_id = request.query_params.get('branch')
        if request.user.role != request.user.Role.ADMIN:
            branch_id = request.user.branch_id
        keyword = request.query_params.get('q', '')
        if not branch_id:
            return Response([])

        records = []
        for report in DailyReport.objects.filter(branch_id=branch_id):
            for e in report.expenses or []:
                records.append((e.get('itemName', ''), e.get('amount', 0), e.get('purpose', ''), report.date))
        for hist in DailyReportHistory.objects.filter(branch_id=branch_id):
            for e in (hist.data or {}).get('expenses', []):
                records.append((e.get('itemName', ''), e.get('amount', 0), e.get('purpose', ''), hist.date))

        by_item = {}
        for item_name, amount, purpose, rec_date in records:
            if not item_name or (keyword and keyword not in item_name):
                continue
            by_item.setdefault(item_name, []).append((amount, purpose, rec_date))

        today = timezone.localdate()
        results = []
        for item_name, entries in by_item.items():
            entries.sort(key=lambda e: e[2], reverse=True)
            latest_amount, latest_purpose, latest_date = entries[0]
            days_since_latest = (today - latest_date).days
            score = len(entries) * 20 + max(0, 60 - days_since_latest)
            results.append({
                'itemName': item_name,
                'lastAmount': latest_amount,
                'lastPurpose': latest_purpose,
                'useCount': len(entries),
                '_score': score,
            })
        results.sort(key=lambda r: r['_score'], reverse=True)
        for r in results:
            r.pop('_score')
        return Response(results[:10])


class DailyReportHistoryViewSet(BranchScopedQuerysetMixin, viewsets.ModelViewSet):
    """Read + create only — history is an append-only audit trail, so
    entries are never updated or deleted once saved."""

    http_method_names = ['get', 'post', 'head', 'options']
    queryset = DailyReportHistory.objects.all()
    serializer_class = DailyReportHistorySerializer
    filterset_fields = ['branch', 'date']
