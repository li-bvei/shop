import django_filters
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from branches.models import Branch
from common.permissions import BranchScopedQuerysetMixin

from .models import (
    Campaign, CheckinMilestone, CheckInRecord, Customer, LotteryDraw, Milestone, Prize, RiskEvent,
    SpendVerification, StaffPermission, Voucher,
)
from .reports import build_campaign_report
from .serializers import (
    CampaignSerializer, CheckInRecordSerializer, CheckinMilestoneSerializer, CustomerDetailSerializer,
    CustomerSerializer, GuestDrawSerializer, GuestLoginSerializer, GuestRecoverSerializer,
    GuestRedeemSerializer, GuestRegisterSerializer, GuestSetPinSerializer, GuestVoucherSerializer,
    LotteryDrawSerializer, MilestoneSerializer, PointsLedgerSerializer, PrizeSerializer,
    RiskEventSerializer, SpendVerificationSerializer, StaffPermissionSerializer, VoucherSerializer,
)
from .services import (
    GUEST_COOKIE_MAX_AGE, GUEST_COOKIE_NAME, AmbiguousGuestLookup, adjust_points, campaign_is_open,
    delete_customer_by_phone, draw_lottery, guest_redeem_voucher, load_store_token, record_checkin,
    recover_card, redeem_points, redeem_voucher, register_customer, resolve_active_campaign,
    set_customer_pin, staff_can, touch_customer_seen, verify_spend, void_spend_verification,
)
from .throttling import GuestReadThrottle, GuestWriteThrottle, StaffVerifyThrottle
from .utils import client_ip, normalize_birthday_md, normalize_phone

STAFF_ROLES = ('staff', 'branch', 'admin')
MANAGER_ROLES = ('branch', 'admin')


class PromotionsPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


def _paginate(view, queryset, serializer_class):
    paginator = PromotionsPagination()
    page = paginator.paginate_queryset(queryset, view.request, view=view)
    return paginator.get_paginated_response(serializer_class(page, many=True).data)


def _guest_cookie_secure():
    return getattr(settings, 'GUEST_COOKIE_SECURE', not settings.DEBUG)


def _set_guest_cookie(response, card_token):
    response.set_cookie(
        GUEST_COOKIE_NAME, card_token,
        max_age=GUEST_COOKIE_MAX_AGE, httponly=True, samesite='Lax',
        secure=_guest_cookie_secure(),
    )
    return response


def _resolve_guest_customer(request):
    """A guest is identified by the pc_guest cookie (same-origin prod) or
    the X-Guest-Token header (cross-port local dev) — both hold the
    Customer.card_token. Nothing else on a public request is trusted. Both
    are tried (header first, since it's what the current client explicitly
    sent) so a stale cookie can't shadow a valid header token."""
    candidates = [
        request.headers.get('X-Guest-Token', ''),
        request.COOKIES.get(GUEST_COOKIE_NAME, ''),
    ]
    for token in candidates:
        token = (token or '').strip()
        if not token:
            continue
        customer = (
            Customer.objects
            .filter(card_token=token, status=Customer.Status.ACTIVE)
            .select_related('organization', 'registered_campaign')
            .first()
        )
        if customer:
            return customer
    return None


def _card_payload(customer, *, include_token=False):
    """The card snapshot both the token-authenticated card page and the
    phone+birthday read-only recovery render. `card_token` is the bearer
    credential for the whole card — it is only ever included for a caller
    that already proved possession of it (GuestCardView). The recovery path
    authenticates on phone + birthday, which the design treats as a weak
    second factor, not a security boundary (打卡与抽奖实施方案.md §14 — a
    stranger who knows your number can view, never take), so it must never
    receive the token back."""
    campaign = customer.registered_campaign
    campaign_active = campaign_is_open(campaign)
    if campaign_active:
        campaign_info = {
            'name': campaign.name,
            'points_per_1000yen': campaign.points_per_1000yen,
            'points_per_draw': campaign.points_per_draw,
            'points_per_voucher': campaign.points_per_voucher,
            'voucher_yen_per_unit': campaign.voucher_yen_per_unit,
            'has_prizes': campaign.prizes.filter(active=True, weight__gt=0).exists(),
        }
        stamp_target = campaign.stamp_target
    else:
        campaign_info = {}
        stamp_target = None
    ledger = customer.points_ledger.select_related('operator').all()[:30]
    vouchers = customer.vouchers.filter(status=Voucher.Status.ACTIVE).order_by('expires_at')[:50]
    milestones = _milestone_progress(customer, campaign) if campaign_active else []
    org = customer.organization
    payload = {
        'name': customer.name,
        'org_name_zh': org.name_zh,
        'org_name_ja': org.name_ja,
        'org_logo_url': org.logo_url,
        'points_balance': customer.points_balance,
        'lifetime_points': customer.lifetime_points_earned,
        'stamp_count': customer.stamp_count,
        'stamp_target': stamp_target,
        'draw_chances': customer.draw_chances,
        'has_pin': bool(customer.pin_hash),
        'campaign': campaign_info,
        'ledger': PointsLedgerSerializer(ledger, many=True).data,
        'vouchers': GuestVoucherSerializer(vouchers, many=True).data,
        'milestones': milestones,
    }
    if include_token:
        payload['card_token'] = customer.card_token
    return payload


def _milestone_progress(customer, campaign):
    claimed = set(customer.milestone_claims.values_list('milestone_id', flat=True))
    rows = []
    for m in campaign.milestones.filter(active=True).order_by('points_threshold'):
        rows.append({
            'threshold': m.points_threshold,
            'label': m.display_label or m.get_reward_type_display(),
            'reached': m.id in claimed or customer.lifetime_points_earned >= m.points_threshold,
            'claimed': m.id in claimed,
        })
    return rows


# ---------------------------------------------------------------------------
# Guest (public) API — AllowAny, no authentication, guest-token scoped.
# ---------------------------------------------------------------------------

class GuestRegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [GuestWriteThrottle]

    def post(self, request):
        serializer = GuestRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        campaign = load_store_token(data['store_token'])
        customer = register_customer(
            organization=campaign.branch.organization,
            phone=data['phone'],
            name=data.get('name', ''),
            birthday_md=data.get('birthday_md', ''),
            pin=data.get('pin', ''),
            consent=data['consent'],
            campaign=campaign,
            ip=client_ip(request),
        )
        if not customer.was_created:
            # The phone already has a card. Don't hand back its credential —
            # direct the (possibly returning, possibly not) caller to the
            # phone+birthday recovery instead.
            return Response({'existing': True}, status=200)

        body = {
            'card_token': customer.card_token,
            'name': customer.name,
            'points_balance': customer.points_balance,
            'stamp_count': customer.stamp_count,
        }
        return _set_guest_cookie(Response(body, status=201), customer.card_token)


class GuestStoreContextView(APIView):
    """Public — resolves a printed store-QR token to just the chain's
    display identity, so the register page can show the brand logo before
    the customer has typed anything. Same vague failure as registration
    (a bad/closed token must not reveal which)."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [GuestReadThrottle]

    def get(self, request):
        campaign = load_store_token(request.query_params.get('t', ''))
        org = campaign.branch.organization
        return Response({
            'org_name_zh': org.name_zh,
            'org_name_ja': org.name_ja,
            'org_logo_url': org.logo_url,
        })


def _recovery_options(customers):
    """The merchant picker payload — the customer holds a card at more than
    one chain, so they choose which to open (each shown with its logo)."""
    return {
        'multiple': True,
        'options': [
            {
                'org': str(c.organization_id),
                'org_name_zh': c.organization.name_zh,
                'org_name_ja': c.organization.name_ja,
                'logo_url': c.organization.logo_url,
            }
            for c in customers
        ],
    }


class GuestLoginView(APIView):
    """Read-only recovery: phone + birthday returns the card snapshot
    directly, no session token. Birthday is a weak second factor, not a
    security boundary (打卡与抽奖实施方案.md §14) — the snapshot can be
    viewed, never spent from. When the pair matches a card at more than one
    chain, returns a picker instead of guessing."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [GuestWriteThrottle]

    def post(self, request):
        serializer = GuestLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            phone = normalize_phone(serializer.validated_data['phone'])
            birthday_md = normalize_birthday_md(serializer.validated_data['birthday_md'])
        except ValidationError:
            raise ValidationError({'detail': ['login-failed']})
        if not birthday_md:
            raise ValidationError({'birthday_md': ['birthday-md-required']})
        org = serializer.validated_data.get('org') or ''

        qs = (
            Customer.objects
            .filter(phone=phone, birthday_md=birthday_md, status=Customer.Status.ACTIVE)
            .select_related('registered_campaign', 'organization')
        )
        if org:
            qs = qs.filter(organization_id=org)
        matches = list(qs[:5])
        if not matches:
            # Same error whether the phone is unknown or the birthday wrong.
            raise ValidationError({'detail': ['login-failed']})
        if len(matches) > 1:
            return Response(_recovery_options(matches))

        customer = matches[0]
        touch_customer_seen(customer)
        payload = _card_payload(customer)
        payload['readonly'] = True
        return Response(payload)


class GuestRecoverView(APIView):
    """Full-access recovery on a new device: phone + birthday + the 6-digit
    PIN. Unlike the read-only login this DOES re-issue the card credential
    — the PIN is the security boundary (per-phone rate limit, no
    self-service reset; a forgotten PIN goes to staff). A triple that
    matches a card at more than one chain returns a picker."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [GuestWriteThrottle]

    def post(self, request):
        serializer = GuestRecoverSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            customer = recover_card(
                phone=serializer.validated_data['phone'],
                pin=serializer.validated_data['pin'],
                birthday_md=serializer.validated_data['birthday_md'],
                org=serializer.validated_data.get('org') or None,
                ip=client_ip(request),
            )
        except AmbiguousGuestLookup as exc:
            return Response(_recovery_options(exc.customers))

        body = {
            'card_token': customer.card_token,
            'name': customer.name,
            'points_balance': customer.points_balance,
            'stamp_count': customer.stamp_count,
        }
        return _set_guest_cookie(Response(body, status=200), customer.card_token)


class GuestSetPinView(APIView):
    """Set / change the recovery PIN for the current card — requires the
    guest token, so you can only set a PIN on a card you already hold."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [GuestWriteThrottle]

    def post(self, request):
        customer = _resolve_guest_customer(request)
        if not customer:
            raise NotFound('card-not-found')
        serializer = GuestSetPinSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        set_customer_pin(customer, serializer.validated_data['pin'])
        return Response({'has_pin': True})


class GuestCardPulseView(APIView):
    """A tiny snapshot the open card page polls (every few seconds) so a
    spend confirmed at the counter animates live without a manual refresh.
    Just the counters — the page pulls the full card only when one of them
    moved."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [GuestReadThrottle]

    def get(self, request):
        customer = _resolve_guest_customer(request)
        if not customer:
            raise NotFound('card-not-found')
        return Response({
            'points_balance': customer.points_balance,
            'lifetime_points': customer.lifetime_points_earned,
            'stamp_count': customer.stamp_count,
            'draw_chances': customer.draw_chances,
            'voucher_count': customer.vouchers.filter(status=Voucher.Status.ACTIVE).count(),
        })


class GuestCardView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [GuestReadThrottle]

    def get(self, request):
        customer = _resolve_guest_customer(request)
        if not customer:
            raise NotFound('card-not-found')
        touch_customer_seen(customer)
        # Rolling renewal so an active card's cookie doesn't lapse. The
        # caller proved token possession, so the payload may echo it back.
        return _set_guest_cookie(
            Response(_card_payload(customer, include_token=True)), customer.card_token,
        )


def _active_campaign_for(customer):
    campaign = customer.registered_campaign
    if not campaign_is_open(campaign):
        raise ValidationError({'campaign': ['no-active-campaign']})
    return campaign


class GuestPrizesView(APIView):
    """The prize pool the customer's wheel draws — names and types only, no
    weights (odds are never exposed). Sold-out prizes are returned too, as
    dimmed segments, so the wheel layout doesn't shift mid-campaign."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [GuestReadThrottle]

    def get(self, request):
        customer = _resolve_guest_customer(request)
        if not customer:
            raise NotFound('card-not-found')
        campaign = _active_campaign_for(customer)
        prizes = campaign.prizes.filter(active=True).order_by('display_order', 'id')
        return Response([
            {
                'id': p.id,
                'name': p.name,
                'reward_type': p.reward_type,
                'sold_out': p.remaining_stock is not None and p.remaining_stock <= 0,
            }
            for p in prizes
        ])


def _draw_result_body(draw):
    voucher = draw.vouchers.first()
    return {
        'draw_id': draw.id,
        'status': draw.status,
        'prize_name': draw.prize_name_snapshot,
        'reward_type': draw.reward_type_snapshot,
        'points_refunded': draw.points_refunded,
        'voucher': GuestVoucherSerializer(voucher).data if voucher else None,
    }


class GuestRedeemView(APIView):
    """Spend points: `type=draw` runs a lottery draw, `type=voucher` issues
    a fixed ¥N next-visit voucher. Idempotent on `request_id`."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [GuestWriteThrottle]

    def post(self, request):
        customer = _resolve_guest_customer(request)
        if not customer:
            raise NotFound('card-not-found')
        serializer = GuestRedeemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        campaign = _active_campaign_for(customer)

        result = redeem_points(
            customer=customer, campaign=campaign, branch=campaign.branch,
            kind=serializer.validated_data['type'],
            request_id=serializer.validated_data['request_id'],
        )
        customer.refresh_from_db()
        body = {'points_balance': customer.points_balance}
        if result['kind'] == 'draw':
            body['result'] = _draw_result_body(result['draw'])
        else:
            body['voucher'] = GuestVoucherSerializer(result['voucher']).data
        return Response(body, status=201)


class GuestDrawView(APIView):
    """Use one free draw chance (granted by the spend-threshold dual track)."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [GuestWriteThrottle]

    def post(self, request):
        customer = _resolve_guest_customer(request)
        if not customer:
            raise NotFound('card-not-found')
        serializer = GuestDrawSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        campaign = _active_campaign_for(customer)

        draw = draw_lottery(
            campaign=campaign, branch=campaign.branch, customer=customer,
            source=LotteryDraw.Source.DIRECT,
            request_id=serializer.validated_data['request_id'],
        )
        customer.refresh_from_db()
        return Response({
            'points_balance': customer.points_balance,
            'draw_chances': customer.draw_chances,
            'result': _draw_result_body(draw),
        }, status=201)


class GuestVoucherRedeemView(APIView):
    """Self-serve redeem for a low-value next-visit item (drink / dessert /
    side dish): the customer slides to confirm on their own phone with
    staff present. Cash vouchers and the chef's special are refused here —
    those go through the staff kiosk."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [GuestWriteThrottle]

    def post(self, request):
        customer = _resolve_guest_customer(request)
        if not customer:
            raise NotFound('card-not-found')
        voucher = guest_redeem_voucher(
            customer=customer,
            redemption_code=request.data.get('redemption_code', ''),
        )
        return Response({'redemption_code': voucher.redemption_code, 'status': voucher.status})


# ---------------------------------------------------------------------------
# Admin / branch — campaigns
# ---------------------------------------------------------------------------

class CampaignViewSet(BranchScopedQuerysetMixin, viewsets.ModelViewSet):
    """admin: every branch in the Organization. branch: its own branch
    only, read + write. staff: blocked (project default)."""

    queryset = Campaign.objects.select_related('branch', 'created_by', 'updated_by').all()
    serializer_class = CampaignSerializer
    filterset_fields = ['branch', 'status']

    def perform_create(self, serializer):
        user = self.request.user
        extra = {'created_by': user, 'updated_by': user}
        if user.role == user.Role.ADMIN:
            branch = serializer.validated_data.get('branch')
            if not branch:
                raise ValidationError({'branch': ['This field is required for admin accounts.']})
            if branch.organization_id != user.organization_id:
                raise ValidationError({'branch': ['branch-outside-organization']})
            serializer.save(**extra)
        else:
            serializer.save(branch_id=user.branch_id, **extra)

    def perform_update(self, serializer):
        # A plain PATCH never moves a campaign between branches (same
        # invariant BranchScopedQuerysetMixin enforces); stamp the editor.
        serializer.save(branch=serializer.instance.branch, updated_by=self.request.user)

    def perform_destroy(self, instance):
        if (instance.spend_verifications.exists() or instance.checkins.exists()
                or instance.draws.exists() or instance.vouchers.exists()):
            raise ValidationError({'detail': ['campaign-has-history']})
        instance.delete()

    @action(detail=True, methods=['get'])
    def checkins(self, request, pk=None):
        qs = self.get_object().checkins.select_related('customer', 'branch').all()
        local_date = request.query_params.get('local_date')
        if local_date:
            qs = qs.filter(local_date=local_date)
        return _paginate(self, qs, CheckInRecordSerializer)

    @action(detail=True, methods=['get'])
    def verifications(self, request, pk=None):
        qs = self.get_object().spend_verifications.select_related('customer', 'branch', 'verified_by').all()
        status_param = request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)
        return _paginate(self, qs, SpendVerificationSerializer)

    @action(detail=True, methods=['get'])
    def draws(self, request, pk=None):
        qs = self.get_object().draws.select_related('customer', 'branch', 'prize').all()
        status_param = request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)
        return _paginate(self, qs, LotteryDrawSerializer)

    @action(detail=True, methods=['get'])
    def vouchers(self, request, pk=None):
        qs = self.get_object().vouchers.select_related('customer').all()
        status_param = request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)
        return _paginate(self, qs, VoucherSerializer)

    @action(detail=True, methods=['get'])
    def report(self, request, pk=None):
        """Monthly operational report — staff-op stats, points flow,
        prize/voucher shipment, risk-flag counts. `?month=YYYY-MM`
        (default: current month)."""
        campaign = self.get_object()
        month_param = request.query_params.get('month') or timezone.localdate().strftime('%Y-%m')
        try:
            year, month = (int(x) for x in month_param.split('-'))
            if not (1 <= month <= 12):
                raise ValueError
        except (ValueError, TypeError):
            raise ValidationError({'month': ['Must be YYYY-MM.']})
        return Response(build_campaign_report(campaign, year, month))


# ---------------------------------------------------------------------------
# Admin / branch / staff(lookup only) — customers
# ---------------------------------------------------------------------------

class CustomerFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(method='filter_search')

    class Meta:
        model = Customer
        fields = ['status']

    def filter_search(self, queryset, name, value):
        value = (value or '').strip()
        if not value:
            return queryset
        return queryset.filter(Q(name__icontains=value) | Q(phone__icontains=value))


class CustomerViewSet(viewsets.ModelViewSet):
    """Organization-scoped (customers are not branch-owned). staff opts in
    only for the `lookup` action; everything else is admin/branch, and
    `points_adjust` / `destroy` are admin-only."""

    permission_classes = [IsAuthenticated]
    serializer_class = CustomerSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = CustomerFilter
    pagination_class = PromotionsPagination
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_queryset(self):
        return Customer.objects.filter(
            organization_id=self.request.user.organization_id,
        ).select_related('registered_campaign')

    def get_serializer_class(self):
        return CustomerDetailSerializer if self.action == 'retrieve' else CustomerSerializer

    def _deny_staff(self):
        if self.request.user.role == self.request.user.Role.STAFF:
            raise PermissionDenied('not-available-for-staff')

    def _require_admin(self):
        if self.request.user.role != self.request.user.Role.ADMIN:
            raise PermissionDenied('admin-only')

    def list(self, request, *args, **kwargs):
        self._deny_staff()
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        self._deny_staff()
        return super().retrieve(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        raise PermissionDenied('customers-are-created-via-guest-register')

    @action(detail=False, methods=['post'])
    def lookup(self, request):
        """Counter scanner / manual phone lookup. Returns only what the
        staff tablet shows — masked phone, never the full number or the
        card token."""
        if request.user.role not in STAFF_ROLES:
            raise PermissionDenied('not-available-for-this-role')
        card_token = (request.data.get('card_token') or '').strip()
        phone_raw = (request.data.get('phone') or '').strip()

        qs = self.get_queryset()
        if card_token:
            customer = qs.filter(card_token=card_token).first()
        elif phone_raw:
            try:
                phone = normalize_phone(phone_raw)
            except ValidationError:
                raise NotFound('customer-not-found')
            customer = qs.filter(phone=phone).first()
        else:
            raise ValidationError({'detail': ['card_token or phone is required']})

        if not customer:
            raise NotFound('customer-not-found')
        if customer.status == Customer.Status.BLOCKED:
            raise PermissionDenied('customer-blocked')

        return Response({
            'id': customer.id,
            'name': customer.name,
            'phone_masked': customer.phone_masked,
            'points_balance': customer.points_balance,
            'stamp_count': customer.stamp_count,
            'stamp_target': (
                customer.registered_campaign.stamp_target if customer.registered_campaign else None
            ),
            'vouchers': [],  # phase 2
        })

    @action(detail=True, methods=['post'], url_path='points-adjust')
    def points_adjust(self, request, pk=None):
        self._require_admin()
        customer = self.get_object()
        entry = adjust_points(
            customer=customer,
            delta=request.data.get('delta'),
            note=request.data.get('note', ''),
            operator=request.user,
        )
        customer.refresh_from_db()
        return Response({
            'ledger_entry': PointsLedgerSerializer(entry).data,
            'points_balance': customer.points_balance,
        }, status=201)

    def destroy(self, request, *args, **kwargs):
        self._require_admin()
        customer = self.get_object()
        result = delete_customer_by_phone(
            organization=request.user.organization, phone=customer.phone, operator=request.user,
        )
        return Response(result, status=200)


# ---------------------------------------------------------------------------
# Staff — spend verification
# ---------------------------------------------------------------------------

class SpendVerificationFilter(django_filters.FilterSet):
    date_from = django_filters.DateFilter(field_name='consumed_at', lookup_expr='date__gte')
    date_to = django_filters.DateFilter(field_name='consumed_at', lookup_expr='date__lte')

    class Meta:
        model = SpendVerification
        fields = ['branch', 'campaign', 'status', 'verified_by']


class SpendVerificationViewSet(viewsets.ModelViewSet):
    """staff/branch/admin create a verification (the trusted event) and read
    their own recent ones (`mine`). Listing everything is branch/admin;
    `void` reverses points and is admin-only. Append-only: update/destroy
    are not routed."""

    permission_classes = [IsAuthenticated]
    serializer_class = SpendVerificationSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = SpendVerificationFilter
    pagination_class = PromotionsPagination
    http_method_names = ['get', 'post', 'head', 'options']

    def get_throttles(self):
        return [StaffVerifyThrottle()] if self.action in ('create', 'checkin') else []

    def get_queryset(self):
        user = self.request.user
        qs = SpendVerification.objects.select_related('customer', 'branch', 'campaign', 'verified_by')
        if user.role == user.Role.ADMIN:
            return qs.filter(branch__organization_id=user.organization_id)
        return qs.filter(branch_id=user.branch_id)

    def list(self, request, *args, **kwargs):
        if request.user.role == request.user.Role.STAFF:
            raise PermissionDenied('not-available-for-staff')
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        if request.user.role == request.user.Role.STAFF:
            raise PermissionDenied('not-available-for-staff')
        return super().retrieve(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        user = request.user
        if user.role not in STAFF_ROLES:
            raise PermissionDenied('not-available-for-this-role')
        if user.role == user.Role.STAFF and not staff_can(user, 'verify_spend'):
            raise PermissionDenied('verify-spend-disabled-for-this-account')

        branch = self._resolve_branch(request, user)
        campaign = self._resolve_campaign(request, branch)
        customer = self._resolve_customer(request, user.organization_id)

        consumed_at = self._parse_consumed_at(request.data.get('consumed_at'))
        verification = verify_spend(
            campaign=campaign, branch=branch, customer=customer,
            amount_yen=request.data.get('amount_yen'),
            table_number=request.data.get('table_number', ''),
            consumed_at=consumed_at,
            verified_by=user, ip=client_ip(request),
            request_id=request.data.get('request_id', ''),
        )
        customer.refresh_from_db()
        return Response({
            'id': verification.id,
            'check_in_id': verification.check_in_record_id,
            'points_granted': verification.points_granted,
            'points_balance': customer.points_balance,
            'stamp_count': customer.stamp_count,
            'risk_level': verification.risk_level,
        }, status=201)

    @action(detail=False, methods=['post'])
    def checkin(self, request):
        """Standalone "customer showed their QR" with no purchase — records
        the visit and issues the daily check-in reward (if the campaign has
        one). Same account rules as a spend confirmation."""
        user = request.user
        if user.role not in STAFF_ROLES:
            raise PermissionDenied('not-available-for-this-role')
        if user.role == user.Role.STAFF and not staff_can(user, 'verify_spend'):
            raise PermissionDenied('verify-spend-disabled-for-this-account')

        branch = self._resolve_branch(request, user)
        campaign = self._resolve_campaign(request, branch)
        customer = self._resolve_customer(request, user.organization_id)

        result = record_checkin(
            campaign=campaign, branch=branch, customer=customer,
            verified_by=user, ip=client_ip(request),
        )
        voucher = result['reward_voucher']
        milestone_vouchers = result.get('milestone_vouchers') or []
        return Response({
            'already_checked_in': result['already_checked_in'],
            'reward_voucher': VoucherSerializer(voucher).data if voucher else None,
            'milestone_vouchers': VoucherSerializer(milestone_vouchers, many=True).data,
        }, status=200 if result['already_checked_in'] else 201)

    @staticmethod
    def _resolve_branch(request, user):
        if user.role == user.Role.ADMIN:
            branch_id = request.data.get('branch')
            if not branch_id:
                # The counter kiosk has no branch picker, so a head-office
                # (admin / 本部) account can't be attributed to a store.
                # Coded so the frontend can show the "use a branch account"
                # message in Japanese.
                raise ValidationError({'branch': ['head-office-account-cannot-scan']})
            branch = Branch.objects.filter(id=branch_id).first()
            if not branch or branch.organization_id != user.organization_id:
                raise ValidationError({'branch': ['branch-outside-organization']})
            return branch
        if not user.branch_id:
            raise ValidationError({'branch': ['account-has-no-branch']})
        return user.branch

    @staticmethod
    def _resolve_campaign(request, branch):
        campaign_id = request.data.get('campaign')
        if campaign_id:
            campaign = Campaign.objects.filter(branch=branch, pk=campaign_id).first()
        else:
            # Several ACTIVE campaigns can coexist (weekday / weekend /
            # Golden Week) — pick the one whose weekday+date rules cover
            # today, highest priority first.
            campaign = resolve_active_campaign(branch)
        if not campaign:
            raise ValidationError({'campaign': ['no-active-campaign-for-branch']})
        return campaign

    @staticmethod
    def _resolve_customer(request, organization_id):
        card_token = (request.data.get('card_token') or '').strip()
        phone_raw = (request.data.get('phone') or '').strip()
        qs = Customer.objects.filter(organization_id=organization_id)
        if card_token:
            customer = qs.filter(card_token=card_token).first()
        elif phone_raw:
            try:
                phone = normalize_phone(phone_raw)
            except ValidationError:
                raise NotFound('customer-not-found')
            customer = qs.filter(phone=phone).first()
        else:
            raise ValidationError({'detail': ['card_token or phone is required']})
        if not customer:
            raise NotFound('customer-not-found')
        return customer

    @staticmethod
    def _parse_consumed_at(raw):
        if not raw:
            return None
        parsed = parse_datetime(raw) if isinstance(raw, str) else None
        if parsed is None:
            raise ValidationError({'consumed_at': ['consumed-at-invalid']})
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed)
        return parsed

    @action(detail=False, methods=['get'])
    def mine(self, request):
        """The current operator's confirmations since local (JST) midnight,
        newest first — the running list the tablet shows after each scan."""
        if request.user.role not in STAFF_ROLES:
            raise PermissionDenied('not-available-for-this-role')
        day_start = timezone.localtime(timezone.now()).replace(hour=0, minute=0, second=0, microsecond=0)
        qs = self.get_queryset().filter(
            verified_by=request.user, created_at__gte=day_start,
        ).order_by('-created_at')[:100]
        return Response(self.get_serializer(qs, many=True).data)

    @action(detail=True, methods=['post'])
    def void(self, request, pk=None):
        if request.user.role != request.user.Role.ADMIN:
            raise PermissionDenied('admin-only')
        result = void_spend_verification(
            verification=self.get_object(), operator=request.user,
            reason=request.data.get('reason', ''),
        )
        return Response(self.get_serializer(result).data)


# ---------------------------------------------------------------------------
# Admin / branch — prize pool & milestones
# ---------------------------------------------------------------------------

def _campaign_in_scope(user, campaign_id):
    """The campaign identified by `campaign_id`, or 400 — restricted to the
    user's Organization (admin) or own branch (branch)."""
    campaign = Campaign.objects.select_related('branch').filter(pk=campaign_id).first()
    if not campaign:
        raise ValidationError({'campaign': ['campaign-not-found']})
    if user.role == user.Role.ADMIN:
        if campaign.branch.organization_id != user.organization_id:
            raise PermissionDenied('campaign-outside-organization')
    elif campaign.branch_id != user.branch_id:
        raise PermissionDenied('campaign-outside-branch')
    return campaign


class _CampaignChildViewSet(viewsets.ModelViewSet):
    """Shared scoping for Prize / Milestone: filtered by `?campaign=`, each
    row's campaign must be in the caller's Organization/branch. staff is
    blocked by the project default. Reads are open to branch + admin;
    writes are **admin only** — prize economics (EV, cost, stock) is a
    chain-level decision (打卡与抽奖实施方案.md §15 decision 09)."""

    pagination_class = None

    def get_queryset(self):
        user = self.request.user
        qs = self.model.objects.select_related('campaign', 'campaign__branch')
        if user.role == user.Role.ADMIN:
            qs = qs.filter(campaign__branch__organization_id=user.organization_id)
        else:
            qs = qs.filter(campaign__branch_id=user.branch_id)
        campaign_id = self.request.query_params.get('campaign')
        if campaign_id:
            qs = qs.filter(campaign_id=campaign_id)
        return qs

    def _require_admin(self):
        if self.request.user.role != self.request.user.Role.ADMIN:
            raise PermissionDenied('prize-and-milestone-management-is-admin-only')

    def perform_create(self, serializer):
        self._require_admin()
        campaign = _campaign_in_scope(self.request.user, self.request.data.get('campaign'))
        serializer.save(campaign=campaign)

    def perform_update(self, serializer):
        self._require_admin()
        serializer.save(campaign=serializer.instance.campaign)

    def perform_destroy(self, instance):
        self._require_admin()
        instance.delete()


class PrizeViewSet(_CampaignChildViewSet):
    model = Prize
    serializer_class = PrizeSerializer

    def get_queryset(self):
        return super().get_queryset().prefetch_related('campaign__prizes')

    def perform_create(self, serializer):
        self._require_admin()
        campaign = _campaign_in_scope(self.request.user, self.request.data.get('campaign'))
        # A limited prize (total_stock set) starts with its full stock
        # available; unlimited keeps remaining_stock null. `remaining_stock`
        # is a read-only serializer field, so it's only ever set here.
        total = serializer.validated_data.get('total_stock')
        serializer.save(campaign=campaign, remaining_stock=total)

    def perform_update(self, serializer):
        self._require_admin()
        prize = serializer.instance
        new_total = serializer.validated_data.get('total_stock', prize.total_stock)
        extra = {'campaign': prize.campaign}
        if new_total != prize.total_stock:
            if new_total is None:
                extra['remaining_stock'] = None
            else:
                consumed = max(0, (prize.total_stock or 0) - (prize.remaining_stock or 0))
                extra['remaining_stock'] = max(0, new_total - consumed)
        serializer.save(**extra)


class MilestoneViewSet(_CampaignChildViewSet):
    model = Milestone
    serializer_class = MilestoneSerializer


class CheckinMilestoneViewSet(_CampaignChildViewSet):
    model = CheckinMilestone
    serializer_class = CheckinMilestoneSerializer


# ---------------------------------------------------------------------------
# Staff — voucher verify & redeem
# ---------------------------------------------------------------------------

class VoucherViewSet(viewsets.ReadOnlyModelViewSet):
    """staff/branch/admin verify + redeem a voucher at checkout. branch/
    admin can also list. A top-prize voucher (`requires_manual_approval`)
    can only be redeemed by a branch/admin account."""

    permission_classes = [IsAuthenticated]
    serializer_class = VoucherSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['status', 'source', 'campaign']
    pagination_class = PromotionsPagination

    def get_queryset(self):
        user = self.request.user
        qs = Voucher.objects.select_related('customer', 'campaign', 'campaign__branch')
        return qs.filter(campaign__branch__organization_id=user.organization_id)

    def list(self, request, *args, **kwargs):
        if request.user.role == request.user.Role.STAFF:
            raise PermissionDenied('not-available-for-staff')
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        if request.user.role == request.user.Role.STAFF:
            raise PermissionDenied('not-available-for-staff')
        return super().retrieve(request, *args, **kwargs)

    def _lookup_vouchers(self, request):
        code = (request.data.get('redemption_code') or '').strip().upper()
        card_token = (request.data.get('card_token') or '').strip()
        phone_raw = (request.data.get('phone') or '').strip()
        name = (request.data.get('name') or '').strip()
        phone_tail = ''.join(ch for ch in (request.data.get('phone_tail') or '') if ch.isdigit())
        qs = self.get_queryset()
        if code:
            return qs.filter(redemption_code=code)
        if card_token:
            return qs.filter(customer__card_token=card_token)
        if phone_raw:
            try:
                phone = normalize_phone(phone_raw)
            except ValidationError:
                raise NotFound('customer-not-found')
            return qs.filter(customer__phone=phone, customer__organization_id=request.user.organization_id)
        if name or phone_tail:
            # Floor staff on a tablet, no scanner: search a customer the
            # guest names + the last digits of their number.
            hit = qs.filter(customer__organization_id=request.user.organization_id)
            if name:
                hit = hit.filter(customer__name__icontains=name)
            if phone_tail:
                hit = hit.filter(customer__phone__endswith=phone_tail)
            return hit
        raise ValidationError({'detail': ['redemption_code, card_token, phone or name is required']})

    @action(detail=False, methods=['post'])
    def verify(self, request):
        if request.user.role not in STAFF_ROLES:
            raise PermissionDenied('not-available-for-this-role')
        vouchers = self._lookup_vouchers(request).order_by('status', 'expires_at')[:50]
        if not vouchers:
            raise NotFound('voucher-not-found')
        now = timezone.now()
        rows = []
        for v in vouchers:
            data = VoucherSerializer(v).data
            data['redeemable'] = v.status == Voucher.Status.ACTIVE and v.expires_at > now
            data['expired'] = v.status == Voucher.Status.EXPIRED or v.expires_at <= now
            rows.append(data)
        return Response(rows)

    @action(detail=False, methods=['post'])
    def redeem(self, request):
        user = request.user
        if user.role not in STAFF_ROLES:
            raise PermissionDenied('not-available-for-this-role')
        if user.role == user.Role.STAFF and not staff_can(user, 'redeem_voucher'):
            raise PermissionDenied('redeem-voucher-disabled-for-this-account')
        code = (request.data.get('redemption_code') or '').strip().upper()
        if not code:
            raise ValidationError({'redemption_code': ['required']})
        voucher = self.get_queryset().filter(redemption_code=code).first()
        if not voucher:
            raise NotFound('voucher-not-found')

        branch = user.branch if user.role != user.Role.ADMIN else None
        if branch is None:
            branch_id = request.data.get('branch')
            if not branch_id:
                # Same rule as spend-verification: a head-office (本部)
                # account can't redeem at the counter — use a branch login.
                raise ValidationError({'branch': ['head-office-account-cannot-scan']})
            branch = Branch.objects.filter(id=branch_id).first()
        if not branch or branch.organization_id != user.organization_id:
            raise ValidationError({'branch': ['branch-required']})

        if voucher.requires_manual_approval and user.role == user.Role.STAFF:
            raise PermissionDenied('manager-approval-required')

        result = redeem_voucher(
            voucher=voucher, branch=branch, operator=user,
            spend_amount_yen=request.data.get('spend_amount_yen'),
            approved_by=user if (voucher.requires_manual_approval and user.role in MANAGER_ROLES) else None,
        )
        return Response(VoucherSerializer(result).data)


# ---------------------------------------------------------------------------
# Admin / branch — risk events & staff permissions (phase 3)
# ---------------------------------------------------------------------------

class RiskEventFilter(django_filters.FilterSet):
    class Meta:
        model = RiskEvent
        fields = ['status', 'event_type', 'severity', 'branch']


class RiskEventViewSet(viewsets.ReadOnlyModelViewSet):
    """Rule-based risk flags. branch sees its own branch's flags (plus
    customer-level flags with no branch); admin sees the whole
    Organization. staff blocked by the project default. Flags are read +
    `review` only — never created or deleted through the API."""

    serializer_class = RiskEventSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = RiskEventFilter
    pagination_class = PromotionsPagination

    def get_queryset(self):
        user = self.request.user
        qs = RiskEvent.objects.filter(
            organization_id=user.organization_id,
        ).select_related('branch', 'customer', 'staff_user', 'reviewed_by')
        if user.role != user.Role.ADMIN:
            qs = qs.filter(Q(branch_id=user.branch_id) | Q(branch__isnull=True))
        return qs

    @action(detail=True, methods=['post'])
    def review(self, request, pk=None):
        event = self.get_object()
        new_status = request.data.get('status')
        if new_status not in (
            RiskEvent.Status.REVIEWED, RiskEvent.Status.CONFIRMED, RiskEvent.Status.DISMISSED,
        ):
            raise ValidationError({'status': ['Must be reviewed / confirmed / dismissed.']})
        event.status = new_status
        event.review_note = (request.data.get('note') or '').strip()[:500]
        event.reviewed_by = request.user
        event.reviewed_at = timezone.now()
        event.save(update_fields=['status', 'review_note', 'reviewed_by', 'reviewed_at'])
        return Response(self.get_serializer(event).data)


class StaffPermissionViewSet(viewsets.ViewSet):
    """admin-only. `{pk}` in every route is the **staff account's user id**
    (not the StaffPermission row id — a row may not exist yet). Lists every
    `staff`-role account in the Organization with its effective switches
    (both-on when no row exists), and lets an admin toggle them."""

    pagination_class = None

    def _require_admin(self):
        if self.request.user.role != self.request.user.Role.ADMIN:
            raise PermissionDenied('admin-only')

    def _staff_user(self, user_id):
        from accounts.models import User

        user = User.objects.filter(
            pk=user_id, organization_id=self.request.user.organization_id, role=User.Role.STAFF,
        ).first()
        if not user:
            raise NotFound('staff-account-not-found')
        return user

    def list(self, request):
        self._require_admin()
        from accounts.models import User

        existing = {
            p.user_id: p
            for p in StaffPermission.objects.filter(
                user__organization_id=request.user.organization_id,
            ).select_related('user')
        }
        rows = []
        for user in User.objects.filter(
            organization_id=request.user.organization_id, role=User.Role.STAFF,
        ).order_by('branch_id', 'username'):
            perm = existing.get(user.id) or StaffPermission(user=user)  # unsaved default
            rows.append(StaffPermissionSerializer(perm).data)
        return Response(rows)

    def retrieve(self, request, pk=None):
        self._require_admin()
        user = self._staff_user(pk)
        perm = StaffPermission.objects.filter(user=user).first() or StaffPermission(user=user)
        return Response(StaffPermissionSerializer(perm).data)

    def partial_update(self, request, pk=None):
        self._require_admin()
        user = self._staff_user(pk)
        perm, _ = StaffPermission.objects.get_or_create(user=user)
        for field in ('can_verify_spend', 'can_redeem_voucher'):
            if field in request.data:
                setattr(perm, field, bool(request.data[field]))
        if 'note' in request.data:
            perm.note = (request.data['note'] or '').strip()[:255]
        perm.updated_by = request.user
        perm.save()
        return Response(StaffPermissionSerializer(perm).data)
