from rest_framework.routers import DefaultRouter

from .views import PaymentMethodDefViewSet

router = DefaultRouter()
router.register('payment-methods', PaymentMethodDefViewSet, basename='payment-method')

urlpatterns = router.urls
