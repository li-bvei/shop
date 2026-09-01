from rest_framework.routers import DefaultRouter

from .views import (
    DabingPersonViewSet,
    DabingRecordViewSet,
    DabingStoreViewSet,
    KyotoDrawBatchViewSet,
    KyotoPersonViewSet,
    KyotoRecordViewSet,
)

router = DefaultRouter()
router.register('lottery/dabing-stores', DabingStoreViewSet, basename='lottery-dabing-store')
router.register('lottery/dabing-people', DabingPersonViewSet, basename='lottery-dabing-person')
router.register('lottery/dabing-records', DabingRecordViewSet, basename='lottery-dabing-record')
router.register('lottery/kyoto-people', KyotoPersonViewSet, basename='lottery-kyoto-person')
router.register('lottery/kyoto-batches', KyotoDrawBatchViewSet, basename='lottery-kyoto-batch')
router.register('lottery/kyoto-records', KyotoRecordViewSet, basename='lottery-kyoto-record')

urlpatterns = router.urls
