from django.contrib import admin
from django.urls import include, path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/', include('accounts.urls')),
    path('api/', include('branches.urls')),
    path('api/', include('staff.urls')),
    path('api/', include('paymentmethods.urls')),
    path('api/', include('dailyreports.urls')),
    path('api/', include('purchasing.urls')),
    path('api/', include('dashboard.urls')),
    path('api/', include('scheduling.urls')),
    path('api/', include('wages.urls')),
    path('api/', include('inventory.urls')),
]
