from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render
from django.utils import timezone
from tasks.models import Task

User = get_user_model()


@login_required
def analytics_dashboard_view(request):
    today = timezone.now().date()

    if request.user.is_admin_role:
        tasks = Task.objects.all()
        # Admin-only user workload breakdown
        user_workloads = User.objects.filter(is_active=True).annotate(
            total_assigned=Count('assigned_tasks'),
            todo=Count('assigned_tasks', filter=Q(assigned_tasks__status=Task.STATUS_TODO)),
            in_progress=Count('assigned_tasks', filter=Q(assigned_tasks__status=Task.STATUS_IN_PROGRESS)),
            completed=Count('assigned_tasks', filter=Q(assigned_tasks__status=Task.STATUS_COMPLETED)),
            overdue=Count('assigned_tasks', filter=Q(assigned_tasks__due_date__lt=today, assigned_tasks__status__in=[Task.STATUS_TODO, Task.STATUS_IN_PROGRESS]))
        ).order_by('-total_assigned')
    else:
        # Strict RBAC: Member only sees their assigned tasks analytics
        tasks = Task.objects.filter(assigned_to=request.user)
        user_workloads = []

    total_tasks = tasks.count()
    completed_tasks = tasks.filter(status=Task.STATUS_COMPLETED).count()
    in_progress_tasks = tasks.filter(status=Task.STATUS_IN_PROGRESS).count()
    todo_tasks = tasks.filter(status=Task.STATUS_TODO).count()
    overdue_tasks = tasks.filter(
        due_date__lt=today,
        status__in=[Task.STATUS_TODO, Task.STATUS_IN_PROGRESS]
    ).count()

    completion_rate = round((completed_tasks / total_tasks * 100), 1) if total_tasks > 0 else 0

    # Status distribution
    status_distribution = {
        'To Do': todo_tasks,
        'In Progress': in_progress_tasks,
        'Completed': completed_tasks,
    }

    # Priority distribution
    priority_distribution = {
        'High': tasks.filter(priority=Task.PRIORITY_HIGH).count(),
        'Medium': tasks.filter(priority=Task.PRIORITY_MEDIUM).count(),
        'Low': tasks.filter(priority=Task.PRIORITY_LOW).count(),
    }

    context = {
        'total_tasks': total_tasks,
        'completed_tasks': completed_tasks,
        'in_progress_tasks': in_progress_tasks,
        'todo_tasks': todo_tasks,
        'overdue_tasks': overdue_tasks,
        'completion_rate': completion_rate,
        'user_workloads': user_workloads,
        'status_distribution': status_distribution,
        'priority_distribution': priority_distribution,
    }
    return render(request, 'analytics/analytics_dashboard.html', context)
