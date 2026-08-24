from rest_framework.routers import DefaultRouter

from .views import ProductViewSet, StockTransactionViewSet, StockViewSet

router = DefaultRouter()
router.register('products', ProductViewSet, basename='product')
router.register('stock', StockViewSet, basename='stock')
router.register('stock-transactions', StockTransactionViewSet, basename='stock-transaction')

urlpatterns = router.urls
