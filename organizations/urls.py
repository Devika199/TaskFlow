from django.urls import path
from . import views

urlpatterns = [
    path('switch/<int:org_id>/', views.switch_organization_view, name='switch_organization'),
    path('settings/', views.organization_settings_view, name='organization_settings'),
]

