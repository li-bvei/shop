from django.contrib.auth.hashers import check_password
from django.core.cache import cache
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from branches.models import Branch
from common.permissions import BranchScopedQuerysetMixin

from .models import CashRegisterDefaults, DailyReport, DailyReportHistory
from .report_lock import UNLOCK_TOKEN_TTL_SECONDS, issue_unlock_token, unlock_token_is_valid
from .serializers import CashRegisterDefaultsSerializer, DailyReportHistorySerializer, DailyReportSerializer


class DailyReportViewSet(BranchScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = DailyReport.objects.all()
    serializer_class = DailyReportSerializer
    filterset_fields = ['branch', 'date']

    def _enforce_report_lock(self, date):
        """A report dated before today is locked once the org has opted in
        (set a non-blank report_unlock_password_hash) — an org that never
        configured one behaves exactly as before this feature existed."""
        org = self.request.user.organization
        if not org.report_unlock_password_hash:
            return
        if date is None or date >= timezone.localdate():
            return
        if not unlock_token_is_valid(self.request):
            raise PermissionDenied('report-locked')

    def perform_create(self, serializer):
        self._enforce_report_lock(serializer.validated_data.get('date'))
        super().perform_create(serializer)

    def perform_update(self, serializer):
        date = serializer.validated_data.get('date') or serializer.instance.date
        self._enforce_report_lock(date)
        super().perform_update(serializer)

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


_UNLOCK_FAIL_LIMIT = 5
_UNLOCK_FAIL_WINDOW_SECONDS = 600


class ReportUnlockView(APIView):
    """POST {password} — checks it against the org's shared unlock password
    and, on success, issues a short-lived token that lets this user's next
    daily-report writes through the date lock (see report_lock.py). Failed
    attempts are rate-limited per user since this is a single shared
    secret, not an individual account password."""

    def post(self, request):
        org = request.user.organization
        if not org.report_unlock_password_hash:
            raise NotFound('report-lock-not-configured')

        fail_key = f'report-unlock-fail:{request.user.id}'
        if cache.get(fail_key, 0) >= _UNLOCK_FAIL_LIMIT:
            raise PermissionDenied('too-many-attempts')

        password = request.data.get('password') or ''
        if not check_password(password, org.report_unlock_password_hash):
            cache.set(fail_key, cache.get(fail_key, 0) + 1, _UNLOCK_FAIL_WINDOW_SECONDS)
            raise ValidationError({'password': ['incorrect-password']})

        cache.delete(fail_key)
        return Response({
            'token': issue_unlock_token(request.user),
            'expires_in_seconds': UNLOCK_TOKEN_TTL_SECONDS,
        })


class CashRegisterDefaultsView(APIView):
    """GET/PATCH /api/cash-register-defaults/?branch=<id> — the branch's
    standing float default for the 5 small denominations plus its レジ固定
    金額 (expected total). `branch` is required for admin accounts (which
    aren't tied to one branch); branch/staff accounts always act on their
    own branch and the query param is ignored for them. Lazily created on
    first access, same convention as accounts.UserPreference."""

    def _resolve_branch(self, request):
        user = request.user
        if user.role == user.Role.ADMIN:
            branch_id = request.query_params.get('branch') or request.data.get('branch')
            if not branch_id:
                raise ValidationError({'branch': ['This field is required for admin accounts.']})
            branch = Branch.objects.filter(id=branch_id, organization_id=user.organization_id).first()
            if not branch:
                raise NotFound('branch-not-found')
            return branch
        if not user.branch_id:
            raise ValidationError({'branch': ['This account has no branch.']})
        return user.branch

    def get(self, request):
        branch = self._resolve_branch(request)
        defaults, _ = CashRegisterDefaults.objects.get_or_create(branch=branch)
        return Response(CashRegisterDefaultsSerializer(defaults).data)

    def patch(self, request):
        branch = self._resolve_branch(request)
        defaults, _ = CashRegisterDefaults.objects.get_or_create(branch=branch)
        serializer = CashRegisterDefaultsSerializer(defaults, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)
        return Response(serializer.data)


class DailyReportHistoryViewSet(BranchScopedQuerysetMixin, viewsets.ModelViewSet):
    """Read + create only — history is an append-only audit trail, so
    entries are never updated or deleted once saved."""

    http_method_names = ['get', 'post', 'head', 'options']
    queryset = DailyReportHistory.objects.all()
    serializer_class = DailyReportHistorySerializer
    filterset_fields = ['branch', 'date']
