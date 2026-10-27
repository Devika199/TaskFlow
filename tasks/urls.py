from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('tasks/', views.task_list_view, name='task_list'),
    path('kanban/', views.kanban_view, name='kanban'),
    path('tasks/create/', views.task_create_view, name='task_create'),
    path('tasks/<int:pk>/', views.task_detail_view, name='task_detail'),
    path('tasks/<int:pk>/edit/', views.task_edit_view, name='task_edit'),
    path('tasks/<int:pk>/status/', views.update_task_status_view, name='update_task_status'),
    path('tasks/<int:pk>/delete/', views.task_delete_view, name='task_delete'),
    path('tasks/<int:pk>/comment/', views.add_comment_view, name='add_comment'),
    path('comments/<int:comment_id>/delete/', views.delete_comment_view, name='delete_comment'),
]
