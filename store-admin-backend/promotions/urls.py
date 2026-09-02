from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    CampaignViewSet, CustomerViewSet, GuestCardPulseView, GuestCardView, GuestDrawView,
    GuestLoginView, GuestPrizesView, GuestRecoverView, GuestRedeemView, GuestRegisterView,
    GuestSetPinView, MilestoneViewSet, PrizeViewSet, RiskEventViewSet, SpendVerificationViewSet,
    StaffPermissionViewSet, VoucherViewSet,
)

router = DefaultRouter()
router.register('promotions/campaigns', CampaignViewSet, basename='promo-campaign')
router.register('promotions/customers', CustomerViewSet, basename='promo-customer')
router.register('promotions/spend-verifications', SpendVerificationViewSet, basename='promo-spend-verification')
router.register('promotions/prizes', PrizeViewSet, basename='promo-prize')
router.register('promotions/milestones', MilestoneViewSet, basename='promo-milestone')
router.register('promotions/vouchers', VoucherViewSet, basename='promo-voucher')
router.register('promotions/risk-events', RiskEventViewSet, basename='promo-risk-event')
router.register('promotions/staff-permissions', StaffPermissionViewSet, basename='promo-staff-permission')

urlpatterns = [
    path('guest/register/', GuestRegisterView.as_view(), name='promo-guest-register'),
    path('guest/login/', GuestLoginView.as_view(), name='promo-guest-login'),
    path('guest/recover/', GuestRecoverView.as_view(), name='promo-guest-recover'),
    path('guest/set-pin/', GuestSetPinView.as_view(), name='promo-guest-set-pin'),
    path('guest/card/', GuestCardView.as_view(), name='promo-guest-card'),
    path('guest/card/pulse/', GuestCardPulseView.as_view(), name='promo-guest-card-pulse'),
    path('guest/prizes/', GuestPrizesView.as_view(), name='promo-guest-prizes'),
    path('guest/redeem/', GuestRedeemView.as_view(), name='promo-guest-redeem'),
    path('guest/draw/', GuestDrawView.as_view(), name='promo-guest-draw'),
    *router.urls,
]
