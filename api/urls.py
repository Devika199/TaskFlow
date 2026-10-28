from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r'tasks', views.TaskViewSet, basename='api_task')
router.register(r'projects', views.ProjectViewSet, basename='api_project')
router.register(r'labels', views.LabelViewSet, basename='api_label')
router.register(r'checklist-items', views.TaskChecklistItemViewSet, basename='api_checklist_item')
router.register(r'comments', views.TaskCommentViewSet, basename='api_comment')
router.register(r'notifications', views.NotificationViewSet, basename='api_notification')

urlpatterns = [
    path('auth/me/', views.CurrentUserAPIView.as_view(), name='api_me'),
    path('analytics/overview/', views.AnalyticsOverviewAPIView.as_view(), name='api_analytics_overview'),
    path('analytics/workload/', views.AnalyticsWorkloadAPIView.as_view(), name='api_analytics_workload'),
    path('users/', views.UsersListAPIView.as_view(), name='api_users'),
    path('', include(router.urls)),
]
