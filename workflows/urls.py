from django.urls import path
from . import views

urlpatterns = [
    path('', views.rule_list_view, name='workflow_rule_list'),
    path('create/', views.rule_create_view, name='workflow_rule_create'),
    path('<int:pk>/edit/', views.rule_edit_view, name='workflow_rule_edit'),
    path('<int:pk>/toggle/', views.rule_toggle_view, name='workflow_rule_toggle'),
    path('<int:pk>/delete/', views.rule_delete_view, name='workflow_rule_delete'),
    path('<int:pk>/history/', views.rule_history_view, name='workflow_rule_history'),
    path('history/', views.all_history_view, name='workflow_history'),
]

