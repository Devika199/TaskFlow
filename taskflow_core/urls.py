from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('tasks.urls')),
    path('', include('accounts.urls')),
    path('notifications/', include('notifications.urls')),
    path('', include('analytics.urls')),
    path('api/v1/', include('api.urls')),
]
