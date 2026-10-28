from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.db.models import Case, IntegerField, Value, When, F
from django.shortcuts import render
from django.utils import timezone
from tasks.models import Task

User = get_user_model()


@login_required
def analytics_dashboard_view(request):
    if not request.user.is_admin_role:
        raise PermissionDenied("Administrator privileges are required to view analytics.")

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


@login_required
def my_analytics_view(request):
    today = timezone.localdate()
    tasks = Task.objects.filter(assigned_to=request.user)
    active_statuses = [Task.STATUS_TODO, Task.STATUS_IN_PROGRESS]

    total_tasks = tasks.count()
    completed_tasks = tasks.filter(status=Task.STATUS_COMPLETED).count()
    in_progress_tasks = tasks.filter(status=Task.STATUS_IN_PROGRESS).count()
    todo_tasks = tasks.filter(status=Task.STATUS_TODO).count()
    overdue_tasks = tasks.filter(
        due_date__lt=today,
        status__in=active_statuses,
    ).count()
    due_today_tasks = tasks.filter(
        due_date=today,
        status__in=active_statuses,
    ).count()
    due_soon_tasks = tasks.filter(
        due_date__gt=today,
        due_date__lte=today + timedelta(days=3),
        status__in=active_statuses,
    ).count()
    completion_rate = round(completed_tasks / total_tasks * 100, 1) if total_tasks else 0

    status_distribution = {
        'To Do': todo_tasks,
        'In Progress': in_progress_tasks,
        'Completed': completed_tasks,
    }
    priority_distribution = {
        'High': tasks.filter(priority=Task.PRIORITY_HIGH).count(),
        'Medium': tasks.filter(priority=Task.PRIORITY_MEDIUM).count(),
        'Low': tasks.filter(priority=Task.PRIORITY_LOW).count(),
    }

    current_week = today - timedelta(days=today.weekday())
    week_starts = [current_week - timedelta(weeks=offset) for offset in range(5, -1, -1)]
    current_timezone = timezone.get_current_timezone()
    weekly_completion = []
    for week_start in week_starts:
        week_end = week_start + timedelta(days=7)
        start_datetime = timezone.make_aware(
            datetime.combine(week_start, time.min),
            current_timezone,
        )
        end_datetime = timezone.make_aware(
            datetime.combine(week_end, time.min),
            current_timezone,
        )
        weekly_completion.append({
            'label': week_start.strftime('%b %d'),
            'count': tasks.filter(
                status=Task.STATUS_COMPLETED,
                completed_at__gte=start_datetime,
                completed_at__lt=end_datetime,
            ).count(),
        })

    urgent_tasks = tasks.filter(status__in=active_statuses).annotate(
        priority_rank=Case(
            When(priority=Task.PRIORITY_HIGH, then=Value(0)),
            When(priority=Task.PRIORITY_MEDIUM, then=Value(1)),
            default=Value(2),
            output_field=IntegerField(),
        ),
    ).select_related('assigned_to').order_by(
        F('due_date').asc(nulls_last=True),
        'priority_rank',
    )[:5]

    chart_data = {
        'status': {
            'labels': list(status_distribution.keys()),
            'values': list(status_distribution.values()),
        },
        'priority': {
            'labels': list(priority_distribution.keys()),
            'values': list(priority_distribution.values()),
        },
        'weekly': {
            'labels': [week['label'] for week in weekly_completion],
            'values': [week['count'] for week in weekly_completion],
        },
    }
    context = {
        'total_tasks': total_tasks,
        'completed_tasks': completed_tasks,
        'in_progress_tasks': in_progress_tasks,
        'todo_tasks': todo_tasks,
        'overdue_tasks': overdue_tasks,
        'due_today_tasks': due_today_tasks,
        'due_soon_tasks': due_soon_tasks,
        'completion_rate': completion_rate,
        'status_distribution': status_distribution,
        'priority_distribution': priority_distribution,
        'weekly_completion': weekly_completion,
        'urgent_tasks': urgent_tasks,
        'chart_data': chart_data,
    }
    return render(request, 'analytics/my_analytics.html', context)
