from django.contrib import admin
from django.urls import include, path
from taskflow_core.views import health_check_view

urlpatterns = [
    path('health/', health_check_view, name='health_check'),
    path('admin/', admin.site.urls),
    path('organizations/', include('organizations.urls')),
    path('workflows/', include('workflows.urls')),
    path('', include('tasks.urls')),
    path('', include('accounts.urls')),
    path('notifications/', include('notifications.urls')),
    path('assistant/', include('ai_assistant.urls')),
    path('', include('analytics.urls')),
    path('api/v1/', include('api.urls')),
]
