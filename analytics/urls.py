from django.urls import path
from . import views

urlpatterns = [
    path('analytics/', views.analytics_dashboard_view, name='analytics_dashboard'),
    path('my-analytics/', views.my_analytics_view, name='my_analytics'),
]
