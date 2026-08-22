from rest_framework.routers import DefaultRouter

from .views import PurchaseRecordViewSet, SupplierViewSet

router = DefaultRouter()
router.register('suppliers', SupplierViewSet, basename='supplier')
router.register('purchases', PurchaseRecordViewSet, basename='purchase')

urlpatterns = router.urls
