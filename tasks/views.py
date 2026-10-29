import calendar
import csv
import io
import json
from datetime import date, datetime, timedelta
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render, reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from notifications.models import Notification
from notifications.services import create_notification
from workflows.events import (
    notify_task_created,
    notify_task_status_changed,
    notify_task_updated,
)
from .forms import (
    LabelForm,
    ProjectForm,
    TaskChecklistItemForm,
    TaskCommentForm,
    TaskForm,
)
from .models import Label, Project, Task, TaskActivityLog, TaskChecklistItem, TaskComment

User = get_user_model()

TASK_SORTS = [
    'due_date', '-due_date', 'priority', '-priority', 'title', '-title',
    'created_at', '-created_at',
]


def _is_org_admin(request):
    if not request.user or not request.user.is_authenticated:
        return False
    membership = getattr(request, 'membership', None)
    if membership:
        return membership.is_admin
    from .models import _get_user_org_cache
    active_ids, admin_ids, has_any = _get_user_org_cache(request.user)
    if has_any:
        org = getattr(request, 'organization', None)
        if org:
            return org.id in admin_ids
        return False
    return bool(request.user.is_admin_role)


def _admin_only(request):
    if not _is_org_admin(request):
        raise PermissionDenied("Only administrators are permitted to manage this resource.")


def _visible_tasks_for_user(user, organization=None):
    tasks = Task.objects.select_related(
        'assigned_to', 'created_by', 'project'
    ).prefetch_related('comments', 'labels', 'checklist_items')
    if organization:
        tasks = tasks.filter(organization=organization)
    membership = user.organization_memberships.filter(organization=organization, is_active=True).first() if organization else None
    is_admin = membership.is_admin if membership else user.is_admin_role
    if not is_admin:
        tasks = tasks.filter(assigned_to=user)
    return tasks


def _visible_task_or_404(request, pk):
    tasks = Task.objects.select_related('created_by', 'assigned_to', 'project').prefetch_related('labels', 'checklist_items')
    if getattr(request, 'organization', None):
        tasks = tasks.filter(organization=request.organization)
    if not _is_org_admin(request):
        tasks = tasks.filter(assigned_to=request.user)
    return get_object_or_404(tasks, pk=pk)


def _visible_project_or_404(request, pk):
    projects = Project.objects.all()
    if getattr(request, 'organization', None):
        projects = projects.filter(organization=request.organization)
    return get_object_or_404(projects, pk=pk)


def _visible_label_or_404(request, pk):
    labels = Label.objects.all()
    if getattr(request, 'organization', None):
        labels = labels.filter(organization=request.organization)
    return get_object_or_404(labels, pk=pk)


def _filtered_task_queryset(request):
    today = timezone.localdate()
    org = getattr(request, 'organization', None)
    tasks = _visible_tasks_for_user(request.user, organization=org)
    q = request.GET.get('q', '').strip()
    if q:
        tasks = tasks.filter(Q(title__icontains=q) | Q(description__icontains=q))

    status = request.GET.get('status', '').strip()
    if status in dict(Task.STATUS_CHOICES):
        tasks = tasks.filter(status=status)

    priority = request.GET.get('priority', '').strip()
    if priority in dict(Task.PRIORITY_CHOICES):
        tasks = tasks.filter(priority=priority)

    project_id = request.GET.get('project', '').strip()
    if project_id.isdigit():
        tasks = tasks.filter(project_id=int(project_id))

    label_id = request.GET.get('label', '').strip()
    if label_id.isdigit():
        tasks = tasks.filter(labels__id=int(label_id))

    assignee = request.GET.get('assigned_to', '').strip()
    if _is_org_admin(request):
        if assignee == 'me':
            tasks = tasks.filter(assigned_to=request.user)
        elif assignee == 'unassigned':
            tasks = tasks.filter(assigned_to__isnull=True)
        elif assignee.isdigit():
            tasks = tasks.filter(assigned_to_id=int(assignee))

    overdue = request.GET.get('overdue', '').strip().lower()
    if overdue in {'1', 'true'}:
        tasks = tasks.filter(due_date__lt=today).exclude(status=Task.STATUS_COMPLETED)

    sort = request.GET.get('sort', '-created_at')
    if sort in TASK_SORTS:
        tasks = tasks.order_by(sort)
    return tasks


def landing_view(request):
    """Public marketing page. Authenticated visitors go to the workspace dashboard."""
    if request.user.is_authenticated:
        return redirect('dashboard')

    return render(request, 'tasks/landing.html')


@login_required
def dashboard_view(request):
    user = request.user
    today = timezone.now().date()
    org = getattr(request, 'organization', None)

    all_tasks = Task.objects.select_related('assigned_to', 'created_by')
    if org:
        all_tasks = all_tasks.filter(organization=org)

    is_admin = _is_org_admin(request)

    if is_admin:
        # System-wide metrics for Admin within active organization
        total_tasks_count = all_tasks.count()
        completed_count = all_tasks.filter(status=Task.STATUS_COMPLETED).count()
        in_progress_count = all_tasks.filter(status=Task.STATUS_IN_PROGRESS).count()
        todo_count = all_tasks.filter(status=Task.STATUS_TODO).count()
        overdue_count = all_tasks.filter(
            due_date__lt=today,
            status__in=[Task.STATUS_TODO, Task.STATUS_IN_PROGRESS]
        ).count()

        completion_rate = round((completed_count / total_tasks_count * 100), 1) if total_tasks_count > 0 else 0

        recent_tasks = all_tasks[:8]
        my_urgent_tasks = all_tasks.filter(
            status__in=[Task.STATUS_TODO, Task.STATUS_IN_PROGRESS]
        ).order_by('due_date', '-priority')[:6]

        activities_qs = TaskActivityLog.objects.select_related('actor', 'task')
        if org:
            activities_qs = activities_qs.filter(task__organization=org)
        recent_activities = activities_qs[:10]

        if org:
            team_workload = User.objects.filter(
                organization_memberships__organization=org,
                organization_memberships__is_active=True,
                is_active=True,
            ).annotate(
                active_tasks=Count('assigned_tasks', filter=Q(assigned_tasks__organization=org, assigned_tasks__status__in=[Task.STATUS_TODO, Task.STATUS_IN_PROGRESS])),
                completed_tasks=Count('assigned_tasks', filter=Q(assigned_tasks__organization=org, assigned_tasks__status=Task.STATUS_COMPLETED)),
                overdue_tasks=Count('assigned_tasks', filter=Q(assigned_tasks__organization=org, assigned_tasks__due_date__lt=today, assigned_tasks__status__in=[Task.STATUS_TODO, Task.STATUS_IN_PROGRESS])),
            ).order_by('-active_tasks')[:8]
        else:
            team_workload = User.objects.filter(is_active=True).annotate(
                active_tasks=Count('assigned_tasks', filter=Q(assigned_tasks__status__in=[Task.STATUS_TODO, Task.STATUS_IN_PROGRESS])),
                completed_tasks=Count('assigned_tasks', filter=Q(assigned_tasks__status=Task.STATUS_COMPLETED)),
                overdue_tasks=Count('assigned_tasks', filter=Q(assigned_tasks__due_date__lt=today, assigned_tasks__status__in=[Task.STATUS_TODO, Task.STATUS_IN_PROGRESS])),
            ).order_by('-active_tasks')[:8]

        priority_counts = {
            'High': all_tasks.filter(priority=Task.PRIORITY_HIGH).count(),
            'Medium': all_tasks.filter(priority=Task.PRIORITY_MEDIUM).count(),
            'Low': all_tasks.filter(priority=Task.PRIORITY_LOW).count(),
        }

        status_counts = {
            'To Do': todo_count,
            'In Progress': in_progress_count,
            'Completed': completed_count,
        }
    else:
        # Member-scoped metrics: strictly assigned to current user within active organization
        my_tasks = all_tasks.filter(assigned_to=user)
        total_tasks_count = my_tasks.count()
        completed_count = my_tasks.filter(status=Task.STATUS_COMPLETED).count()
        in_progress_count = my_tasks.filter(status=Task.STATUS_IN_PROGRESS).count()
        todo_count = my_tasks.filter(status=Task.STATUS_TODO).count()
        overdue_count = my_tasks.filter(
            due_date__lt=today,
            status__in=[Task.STATUS_TODO, Task.STATUS_IN_PROGRESS]
        ).count()

        completion_rate = round((completed_count / total_tasks_count * 100), 1) if total_tasks_count > 0 else 0

        recent_tasks = my_tasks[:8]
        my_urgent_tasks = my_tasks.filter(
            status__in=[Task.STATUS_TODO, Task.STATUS_IN_PROGRESS]
        ).order_by('due_date', '-priority')[:6]

        activities_qs = TaskActivityLog.objects.filter(task__assigned_to=user).select_related('actor', 'task')
        if org:
            activities_qs = activities_qs.filter(task__organization=org)
        recent_activities = activities_qs[:10]
        team_workload = []

        priority_counts = {
            'High': my_tasks.filter(priority=Task.PRIORITY_HIGH).count(),
            'Medium': my_tasks.filter(priority=Task.PRIORITY_MEDIUM).count(),
            'Low': my_tasks.filter(priority=Task.PRIORITY_LOW).count(),
        }

        status_counts = {
            'To Do': todo_count,
            'In Progress': in_progress_count,
            'Completed': completed_count,
        }

    context = {
        'total_tasks_count': total_tasks_count,
        'completed_count': completed_count,
        'in_progress_count': in_progress_count,
        'todo_count': todo_count,
        'overdue_count': overdue_count,
        'completion_rate': completion_rate,
        'recent_tasks': recent_tasks,
        'my_urgent_tasks': my_urgent_tasks,
        'recent_activities': recent_activities,
        'team_workload': team_workload,
        'priority_counts': priority_counts,
        'status_counts': status_counts,
    }
    return render(request, 'tasks/dashboard.html', context)


@login_required
def task_list_view(request):
    today = timezone.now().date()
    org = getattr(request, 'organization', None)
    is_admin = _is_org_admin(request)
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip()
    priority = request.GET.get('priority', '').strip()
    project_id = request.GET.get('project', '').strip()
    label_id = request.GET.get('label', '').strip()
    assignee = request.GET.get('assigned_to', '').strip()
    if not is_admin:
        assignee = 'me'
    overdue = request.GET.get('overdue', '').strip()
    sort = request.GET.get('sort', '-created_at')
    tasks = _filtered_task_queryset(request)

    if org:
        users = User.objects.filter(
            organization_memberships__organization=org,
            organization_memberships__is_active=True,
            is_active=True,
        ).distinct().order_by('first_name', 'username')
        projects = Project.objects.filter(organization=org)
        labels = Label.objects.filter(organization=org)
    else:
        users = User.objects.filter(is_active=True).order_by('first_name', 'username')
        projects = Project.objects.all()
        labels = Label.objects.all()

    if not is_admin:
        projects = projects.filter(tasks__assigned_to=request.user).distinct()
    projects = projects.order_by('name')

    # Scoped metric counts for top pills
    base_tasks = Task.objects.all()
    if org:
        base_tasks = base_tasks.filter(organization=org)

    if is_admin:
        all_count = base_tasks.count()
        my_count = base_tasks.filter(assigned_to=request.user).count()
        overdue_count = base_tasks.filter(due_date__lt=today).exclude(status=Task.STATUS_COMPLETED).count()
    else:
        all_count = base_tasks.filter(assigned_to=request.user).count()
        my_count = all_count
        overdue_count = base_tasks.filter(assigned_to=request.user, due_date__lt=today).exclude(status=Task.STATUS_COMPLETED).count()

    context = {
        'tasks': tasks,
        'users': users,
        'current_q': q,
        'current_status': status,
        'current_priority': priority,
        'current_project': project_id,
        'current_label': label_id,
        'projects': projects,
        'labels': labels,
        'current_assignee': assignee,
        'current_overdue': overdue,
        'current_sort': sort,
        'all_count': all_count,
        'my_count': my_count,
        'overdue_count': overdue_count,
    }
    return render(request, 'tasks/task_list.html', context)


@login_required
def task_calendar_view(request):
    org = getattr(request, 'organization', None)
    is_admin = _is_org_admin(request)
    month_value = request.GET.get('month', '')
    try:
        selected_month = datetime.strptime(month_value, '%Y-%m').date().replace(day=1) if month_value else timezone.localdate().replace(day=1)
    except ValueError:
        selected_month = timezone.localdate().replace(day=1)

    month_start = selected_month
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    previous_month = (month_start - timedelta(days=1)).replace(day=1)
    month_end = next_month - timezone.timedelta(days=1)

    tasks = _visible_tasks_for_user(request.user, organization=org).filter(
        due_date__gte=month_start,
        due_date__lte=month_end,
    )
    assignee = request.GET.get('assigned_to', '').strip()
    if is_admin:
        if assignee == 'me':
            tasks = tasks.filter(assigned_to=request.user)
        elif assignee == 'unassigned':
            tasks = tasks.filter(assigned_to__isnull=True)
        elif assignee.isdigit():
            tasks = tasks.filter(assigned_to_id=int(assignee))
    else:
        assignee = 'me'

    tasks_by_day = {}
    for task in tasks.order_by('due_date', 'priority', 'title'):
        tasks_by_day.setdefault(task.due_date, []).append(task)

    weeks = []
    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(
        selected_month.year,
        selected_month.month,
    ):
        weeks.append([
            {
                'date': day,
                'in_month': day.month == selected_month.month,
                'is_today': day == timezone.localdate(),
                'tasks': tasks_by_day.get(day, []),
            }
            for day in week
        ])

    if org:
        users = User.objects.filter(
            organization_memberships__organization=org,
            organization_memberships__is_active=True,
            is_active=True,
        ).distinct().order_by('first_name', 'username')
    else:
        users = User.objects.filter(is_active=True).order_by('first_name', 'username')

    return render(request, 'tasks/calendar.html', {
        'weeks': weeks,
        'weekdays': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
        'month_title': selected_month.strftime('%B %Y'),
        'current_month': selected_month.strftime('%Y-%m'),
        'previous_month': previous_month.strftime('%Y-%m'),
        'next_month': next_month.strftime('%Y-%m'),
        'current_assignee': assignee,
        'users': users,
    })


@login_required
def task_palette_search_view(request):
    query = request.GET.get('q', '').strip()[:100]
    if len(query) < 2:
        return JsonResponse({'results': []})

    org = getattr(request, 'organization', None)
    tasks = _visible_tasks_for_user(request.user, organization=org).filter(
        Q(title__icontains=query) | Q(description__icontains=query)
    ).order_by('-updated_at')[:10]
    return JsonResponse({
        'results': [
            {
                'id': task.pk,
                'title': task.title,
                'status': task.get_status_display(),
                'priority': task.get_priority_display(),
                'url': reverse('task_detail', args=[task.pk]),
            }
            for task in tasks
        ],
    })


@login_required
def task_csv_export_view(request):
    if not _is_org_admin(request):
        raise PermissionDenied("Only administrators may export the task list.")

    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['Task', 'Description', 'Status', 'Priority', 'Due date', 'Assignee', 'Project', 'Labels'])
    for task in _filtered_task_queryset(request):
        row = [
            task.title,
            task.description,
            task.get_status_display(),
            task.get_priority_display(),
            task.due_date.isoformat() if task.due_date else '',
            task.assigned_to.username if task.assigned_to else '',
            task.project.name if task.project else '',
            ', '.join(label.name for label in task.labels.all()),
        ]
        writer.writerow([
            "'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@')) else value
            for value in row
        ])

    response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="taskflow-tasks-{timezone.localdate().isoformat()}.csv"'
    return response


@login_required
def kanban_view(request):
    org = getattr(request, 'organization', None)
    is_admin = _is_org_admin(request)
    tasks = _visible_tasks_for_user(request.user, organization=org)

    q = request.GET.get('q', '').strip()
    if q:
        tasks = tasks.filter(Q(title__icontains=q) | Q(description__icontains=q))

    priority = request.GET.get('priority', '').strip()
    if priority in dict(Task.PRIORITY_CHOICES):
        tasks = tasks.filter(priority=priority)

    project_id = request.GET.get('project', '').strip()
    if project_id.isdigit():
        tasks = tasks.filter(project_id=int(project_id))

    label_id = request.GET.get('label', '').strip()
    if label_id.isdigit():
        tasks = tasks.filter(labels__id=int(label_id))

    assignee = request.GET.get('assigned_to', '').strip()
    if is_admin:
        if assignee == 'me':
            tasks = tasks.filter(assigned_to=request.user)
        elif assignee.isdigit():
            tasks = tasks.filter(assigned_to_id=int(assignee))
    else:
        assignee = 'me'

    todo_tasks = [t for t in tasks if t.status == Task.STATUS_TODO]
    in_progress_tasks = [t for t in tasks if t.status == Task.STATUS_IN_PROGRESS]
    completed_tasks = [t for t in tasks if t.status == Task.STATUS_COMPLETED]

    if org:
        users = User.objects.filter(
            organization_memberships__organization=org,
            organization_memberships__is_active=True,
            is_active=True,
        ).distinct().order_by('first_name', 'username')
        projects = Project.objects.filter(organization=org)
        labels = Label.objects.filter(organization=org)
    else:
        users = User.objects.filter(is_active=True).order_by('first_name', 'username')
        projects = Project.objects.all()
        labels = Label.objects.all()

    if not is_admin:
        projects = projects.filter(tasks__assigned_to=request.user).distinct()
    projects = projects.order_by('name')

    context = {
        'todo_tasks': todo_tasks,
        'in_progress_tasks': in_progress_tasks,
        'completed_tasks': completed_tasks,
        'users': users,
        'current_q': q,
        'current_priority': priority,
        'current_project': project_id,
        'current_label': label_id,
        'projects': projects,
        'labels': labels,
        'current_assignee': assignee,
    }
    return render(request, 'tasks/kanban.html', context)


@login_required
def task_detail_view(request, pk):
    task = _visible_task_or_404(request, pk)

    comments = task.comments.filter(parent__isnull=True).select_related('author').prefetch_related(
        'replies', 'replies__author'
    )
    activity_logs = task.activity_logs.select_related('actor')[:15]
    comment_form = TaskCommentForm()

    context = {
        'task': task,
        'comments': comments,
        'activity_logs': activity_logs,
        'comment_form': comment_form,
        'can_edit': task.can_edit(request.user),
        'can_delete': task.can_delete(request.user),
        'can_update_status': task.can_update_status(request.user),
    }
    return render(request, 'tasks/task_detail.html', context)


@login_required
def task_create_view(request):
    # Strict RBAC: Only Admin can create tasks
    if not _is_org_admin(request):
        raise PermissionDenied("Only administrators are permitted to create tasks.")

    org = getattr(request, 'organization', None)
    if request.method == 'POST':
        form = TaskForm(request.POST, user=request.user, organization=org)
        if form.is_valid():
            task = form.save(commit=False)
            task.created_by = request.user
            if org:
                task.organization = org
            task.save()
            form.save_m2m()

            TaskActivityLog.objects.create(
                task=task,
                actor=request.user,
                action='CREATED',
                details=f"Task '{task.title}' created by {request.user.display_name}."
            )

            # Notify assignee if assigned to someone else
            if task.assigned_to and task.assigned_to != request.user:
                create_notification(
                    recipient=task.assigned_to,
                    actor=request.user,
                    verb=f"assigned you to task '{task.title}'",
                    task=task,
                    notification_type=Notification.TYPE_ASSIGNMENT
                )

            notify_task_created(task, actor=request.user)

            messages.success(request, f"Task '{task.title}' created successfully!")
            return redirect('task_detail', pk=task.pk)
        else:
            messages.error(request, "Please check the form for errors.")
    else:
        initial = {}
        if 'status' in request.GET and request.GET['status'] in dict(Task.STATUS_CHOICES):
            initial['status'] = request.GET['status']
        if 'project' in request.GET:
            try:
                initial['project'] = int(request.GET['project'])
            except (ValueError, TypeError):
                pass
        form = TaskForm(initial=initial, user=request.user, organization=org)

    return render(request, 'tasks/task_form.html', {'form': form, 'title': 'Create New Task', 'action_label': 'Create Task'})


@login_required
def task_edit_view(request, pk):
    task = _visible_task_or_404(request, pk)

    # Strict RBAC: Only Admin can edit task details or reassign tasks
    if not _is_org_admin(request):
        raise PermissionDenied("Only administrators are permitted to edit task details.")

    org = getattr(request, 'organization', None)
    old_status = task.status
    old_assignee = task.assigned_to
    old_project = task.project
    old_labels = set(task.labels.all())

    if request.method == 'POST':
        form = TaskForm(request.POST, instance=task, user=request.user, organization=org)
        if form.is_valid():
            updated_task = form.save()
            changes = []

            # Check status change
            if old_status != updated_task.status:
                changes.append(f"Status changed from {old_status} to {updated_task.status}")
                if updated_task.assigned_to and old_assignee == updated_task.assigned_to:
                    create_notification(
                        recipient=updated_task.assigned_to,
                        actor=request.user,
                        verb=f"updated status of '{updated_task.title}' to {updated_task.get_status_display()}",
                        task=updated_task,
                        notification_type=Notification.TYPE_STATUS_CHANGE
                    )

            # Check assignee change
            if old_assignee != updated_task.assigned_to:
                new_name = updated_task.assigned_to.display_name if updated_task.assigned_to else "Unassigned"
                changes.append(f"Reassigned to {new_name}")
                if updated_task.assigned_to:
                    create_notification(
                        recipient=updated_task.assigned_to,
                        actor=request.user,
                        verb=f"assigned you to task '{updated_task.title}'",
                        task=updated_task,
                        notification_type=Notification.TYPE_ASSIGNMENT
                    )

            # Check project change
            if old_project != updated_task.project:
                proj_name = updated_task.project.name if updated_task.project else "None"
                changes.append(f"Project set to {proj_name}")

            # Check labels change
            new_labels = set(updated_task.labels.all())
            if old_labels != new_labels:
                lbl_names = ", ".join(l.name for l in new_labels) if new_labels else "None"
                changes.append(f"Labels updated: {lbl_names}")

            details_str = "; ".join(changes) if changes else "Task details updated."
            TaskActivityLog.objects.create(
                task=updated_task,
                actor=request.user,
                action='UPDATED',
                details=details_str
            )

            notify_task_updated(
                updated_task,
                actor=request.user,
                old_status=old_status,
                old_assignee=old_assignee,
            )

            messages.success(request, f"Task '{updated_task.title}' updated successfully.")
            return redirect('task_detail', pk=updated_task.pk)
        else:
            messages.error(request, "Please fix the errors below.")
    else:
        form = TaskForm(instance=task, user=request.user, organization=org)

    return render(request, 'tasks/task_form.html', {'form': form, 'title': f'Edit: {task.title}', 'action_label': 'Save Changes', 'task': task})


@login_required
def task_delete_view(request, pk):
    task = _visible_task_or_404(request, pk)

    # Strict RBAC: Only Admin can delete tasks
    if not _is_org_admin(request):
        raise PermissionDenied("Only administrators are permitted to delete tasks.")

    if request.method == 'POST':
        title = task.title
        task.delete()
        messages.success(request, f"Task '{title}' was permanently deleted.")
        return redirect('task_list')

    return render(request, 'tasks/task_confirm_delete.html', {'task': task})


@login_required
@require_POST
def update_task_status_view(request, pk):
    """
    Explicit status update view permitted for:
    - Admin (all tasks)
    - Member (only their assigned tasks)
    """
    task = _visible_task_or_404(request, pk)

    if not task.can_update_status(request.user):
        raise PermissionDenied("You are not authorized to update the status of this task.")

    new_status = request.POST.get('status')
    if not new_status and request.content_type == 'application/json':
        try:
            body = json.loads(request.body)
            new_status = body.get('status')
        except Exception:
            pass

    if new_status not in dict(Task.STATUS_CHOICES):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
            return JsonResponse({'error': 'Invalid task status choice.'}, status=400)
        messages.error(request, "Invalid task status choice.")
        return redirect('task_detail', pk=task.pk)

    old_status = task.status
    if old_status != new_status:
        task.status = new_status
        task.save()

        TaskActivityLog.objects.create(
            task=task,
            actor=request.user,
            action='STATUS_CHANGE',
            details=f"Status changed from {old_status} to {new_status}"
        )

        # Notify creator or assignee
        target = task.created_by if request.user == task.assigned_to else task.assigned_to
        if target:
            create_notification(
                recipient=target,
                actor=request.user,
                verb=f"moved '{task.title}' to {task.get_status_display()}",
                task=task,
                notification_type=Notification.TYPE_STATUS_CHANGE
            )

        notify_task_status_changed(task, actor=request.user, old_status=old_status)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
        return JsonResponse({
            'success': True,
            'id': task.id,
            'status': task.status,
            'status_display': task.get_status_display(),
            'message': f"Task status updated to {task.get_status_display()}."
        })

    messages.success(request, f"Status updated to {task.get_status_display()}.")
    return redirect('task_detail', pk=task.pk)


@login_required
def add_comment_view(request, pk):
    task = _visible_task_or_404(request, pk)

    # Strict RBAC: Member can only comment on tasks assigned to them
    if not task.can_comment(request.user):
        raise PermissionDenied("You are not authorized to comment on this task.")

    if request.method == 'POST':
        content = request.POST.get('content', '').strip()
        if not content:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
                return JsonResponse({'error': 'Comment content cannot be empty.'}, status=400)
            messages.error(request, "Comment content cannot be empty.")
            return redirect('task_detail', pk=task.pk)

        form = TaskCommentForm(request.POST)
        form.fields['parent'].queryset = task.comments.all()
        if form.is_valid():
            comment = form.save(commit=False)
            comment.task = task
            comment.author = request.user
            comment.save()

            TaskActivityLog.objects.create(
                task=task,
                actor=request.user,
                action='COMMENT_ADDED',
                details=f"{request.user.display_name} added a comment."
            )

            # Notify assignee and creator if someone else commented
            recipients = set(filter(None, [task.assigned_to, task.created_by]))
            for recipient in recipients:
                create_notification(
                    recipient=recipient,
                    actor=request.user,
                    verb=f"commented on '{task.title}'",
                    task=task,
                    notification_type=Notification.TYPE_COMMENT
                )

            # AJAX response support
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
                return JsonResponse({
                    'success': True,
                    'comment': {
                        'id': comment.id,
                        'author_name': comment.author.display_name,
                        'author_initials': comment.author.initials,
                        'author_color': comment.author.avatar_color,
                        'content': comment.content,
                        'created_at': comment.created_at.strftime('%b %d, %Y %H:%M'),
                        'parent_id': comment.parent_id,
                    }
                })

            messages.success(request, "Comment posted.")
            return redirect('task_detail', pk=task.pk)

    messages.error(request, "Failed to post comment.")
    return redirect('task_detail', pk=task.pk)


@login_required
def delete_comment_view(request, comment_id):
    org = getattr(request, 'organization', None)
    comments = TaskComment.objects.select_related('task')
    if org:
        comments = comments.filter(task__organization=org)
    if not _is_org_admin(request):
        comments = comments.filter(task__assigned_to=request.user)
    comment = get_object_or_404(comments, pk=comment_id)
    task_pk = comment.task.pk

    if not comment.can_delete(request.user):
        raise PermissionDenied("You do not have permission to delete this comment.")

    if request.method == 'POST':
        comment.delete()
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': True})
        messages.success(request, "Comment deleted.")

    return redirect('task_detail', pk=task_pk)


def _record_checklist_activity(task, actor, details):
    TaskActivityLog.objects.create(
        task=task,
        actor=actor,
        action='CHECKLIST_UPDATED',
        details=details,
    )


@login_required
def checklist_add_view(request, pk):
    task = _visible_task_or_404(request, pk)
    _admin_only(request)
    if request.method == 'POST':
        form = TaskChecklistItemForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.task = task
            item.position = task.checklist_items.count()
            item.save()
            _record_checklist_activity(task, request.user, f"Added checklist item '{item.title}'.")
            messages.success(request, "Checklist item added.")
            return redirect('task_detail', pk=task.pk)
    else:
        form = TaskChecklistItemForm()
    return render(request, 'tasks/checklist_item_form.html', {
        'form': form,
        'task': task,
        'title': 'Add checklist item',
    })


@login_required
def checklist_edit_view(request, pk, item_id):
    task = _visible_task_or_404(request, pk)
    _admin_only(request)
    item = get_object_or_404(TaskChecklistItem, pk=item_id, task=task)
    if request.method == 'POST':
        form = TaskChecklistItemForm(request.POST, instance=item)
        if form.is_valid():
            item = form.save()
            _record_checklist_activity(task, request.user, f"Updated checklist item '{item.title}'.")
            messages.success(request, "Checklist item updated.")
            return redirect('task_detail', pk=task.pk)
    else:
        form = TaskChecklistItemForm(instance=item)
    return render(request, 'tasks/checklist_item_form.html', {
        'form': form,
        'task': task,
        'title': 'Edit checklist item',
        'item': item,
    })


@login_required
@require_POST
def checklist_delete_view(request, pk, item_id):
    task = _visible_task_or_404(request, pk)
    _admin_only(request)
    item = get_object_or_404(TaskChecklistItem, pk=item_id, task=task)
    title = item.title
    item.delete()
    _record_checklist_activity(task, request.user, f"Deleted checklist item '{title}'.")
    messages.success(request, "Checklist item deleted.")
    return redirect('task_detail', pk=task.pk)


@login_required
@require_POST
def checklist_toggle_view(request, pk, item_id):
    task = _visible_task_or_404(request, pk)
    item = get_object_or_404(TaskChecklistItem, pk=item_id, task=task)
    item.is_completed = not item.is_completed
    item.save(update_fields=['is_completed', 'updated_at'])
    _record_checklist_activity(
        task,
        request.user,
        f"Marked checklist item '{item.title}' {'complete' if item.is_completed else 'incomplete'}.",
    )
    return redirect('task_detail', pk=task.pk)


@login_required
@require_POST
def checklist_reorder_view(request, pk, item_id):
    task = _visible_task_or_404(request, pk)
    _admin_only(request)
    item = get_object_or_404(TaskChecklistItem, pk=item_id, task=task)
    direction = request.POST.get('direction')
    if direction not in {'up', 'down'}:
        messages.error(request, "Choose a valid checklist order.")
        return redirect('task_detail', pk=task.pk)
    siblings = list(task.checklist_items.all())
    index = siblings.index(item)
    swap_index = index - 1 if direction == 'up' else index + 1
    if 0 <= swap_index < len(siblings):
        other = siblings[swap_index]
        item.position, other.position = other.position, item.position
        item.save(update_fields=['position', 'updated_at'])
        other.save(update_fields=['position', 'updated_at'])
        _record_checklist_activity(task, request.user, f"Reordered checklist item '{item.title}'.")
    return redirect('task_detail', pk=task.pk)


@login_required
def projects_view(request):
    _admin_only(request)
    org = getattr(request, 'organization', None)
    if request.method == 'POST':
        form = ProjectForm(request.POST, organization=org)
        if form.is_valid():
            project = form.save(commit=False)
            project.created_by = request.user
            if org:
                project.organization = org
            project.save()
            messages.success(request, f"Project '{project.name}' created.")
            return redirect('projects')
    else:
        form = ProjectForm(organization=org)

    projects_qs = Project.objects.annotate(task_count=Count('tasks'))
    if org:
        projects_qs = projects_qs.filter(organization=org)

    return render(request, 'tasks/projects.html', {
        'projects': projects_qs.order_by('archived', 'name'),
        'form': form,
    })


@login_required
def project_edit_view(request, pk):
    _admin_only(request)
    project = _visible_project_or_404(request, pk)
    org = getattr(request, 'organization', None)
    if request.method == 'POST':
        form = ProjectForm(request.POST, instance=project, organization=org)
        if form.is_valid():
            project = form.save()
            messages.success(request, f"Project '{project.name}' updated.")
            return redirect('projects')
    else:
        form = ProjectForm(instance=project, organization=org)
    return render(request, 'tasks/project_form.html', {
        'project': project,
        'form': form,
        'title': f'Edit {project.name}',
    })


@login_required
@require_POST
def project_archive_view(request, pk):
    _admin_only(request)
    project = _visible_project_or_404(request, pk)
    project.archived = not project.archived
    project.save(update_fields=['archived', 'updated_at'])
    action = 'archived' if project.archived else 'restored'
    messages.success(request, f"Project '{project.name}' {action}.")
    return redirect('projects')


@login_required
def labels_view(request):
    _admin_only(request)
    org = getattr(request, 'organization', None)
    if request.method == 'POST':
        form = LabelForm(request.POST, organization=org)
        if form.is_valid():
            label = form.save(commit=False)
            if org:
                label.organization = org
            label.save()
            messages.success(request, f"Label '{label.name}' created.")
            return redirect('labels')
    else:
        form = LabelForm(organization=org)

    labels_qs = Label.objects.all()
    if org:
        labels_qs = labels_qs.filter(organization=org)

    return render(request, 'tasks/labels.html', {
        'labels': labels_qs.order_by('name'),
        'form': form,
    })


@login_required
def label_edit_view(request, pk):
    _admin_only(request)
    label = _visible_label_or_404(request, pk)
    org = getattr(request, 'organization', None)
    if request.method == 'POST':
        form = LabelForm(request.POST, instance=label, organization=org)
        if form.is_valid():
            label = form.save()
            messages.success(request, f"Label '{label.name}' updated.")
            return redirect('labels')
    else:
        form = LabelForm(instance=label, organization=org)
    return render(request, 'tasks/label_form.html', {
        'label': label,
        'form': form,
        'title': f'Edit {label.name}',
    })


@login_required
@require_POST
def label_delete_view(request, pk):
    _admin_only(request)
    label = _visible_label_or_404(request, pk)
    label.delete()
    messages.success(request, "Label deleted.")
    return redirect('labels')

