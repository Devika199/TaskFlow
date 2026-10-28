"""Synchronous TaskFlow operations exposed through the MCP server."""

import os
from datetime import date
from typing import TypedDict

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from mcp.server.mcpserver.exceptions import ToolError
from rest_framework import serializers

from accounts.models import User
from api.serializers import TaskStatusUpdateSerializer
from notifications.models import Notification
from notifications.services import create_notification
from tasks.forms import TaskForm
from tasks.models import Task, TaskActivityLog

MAX_TASK_DESCRIPTION_LENGTH = 10_000
MAX_TASK_LIST_LIMIT = 100


class TaskRecord(TypedDict):
    """Public, non-sensitive task data returned by MCP tools."""

    id: int
    title: str
    description: str
    status: str
    status_display: str
    priority: str
    priority_display: str
    due_date: str | None
    due_status: str
    is_overdue: bool
    created_by: str | None
    assigned_to: str | None
    project: str | None
    labels: list[dict[str, str]]
    created_at: str
    updated_at: str


class TaskListResult(TypedDict):
    """A bounded collection of tasks."""

    count: int
    tasks: list[TaskRecord]


class TaskSummary(TypedDict):
    """Task counts within the caller's permitted scope."""

    scope: str
    total: int
    completed: int
    in_progress: int
    todo: int
    overdue: int
    completion_rate: float


class TaskDetails(TaskRecord):
    """A task and its recent collaboration history."""

    activity: list[dict[str, str | None]]
    comments: list[dict[str, int | str | None]]
    checklist_items: list[dict[str, int | str | bool]]


class TaskMutationResult(TypedDict):
    """Result of a task write operation."""

    task: TaskRecord
    changed: bool


def _get_active_user() -> User:
    username = os.environ.get("TASKFLOW_MCP_USER", "").strip()
    if not username:
        raise ToolError("TASKFLOW_MCP_USER is not set.")

    try:
        return User.objects.get(username=username, is_active=True)
    except User.DoesNotExist as exc:
        raise ToolError("The configured TaskFlow user is missing or inactive.") from exc


def _visible_tasks(user: User) -> QuerySet[Task]:
    tasks = Task.objects.select_related(
        "created_by", "assigned_to", "project"
    ).prefetch_related("labels", "checklist_items")
    if not user.is_admin_role:
        tasks = tasks.filter(assigned_to=user)
    return tasks


def _get_visible_task(user: User, task_id: int) -> Task:
    if isinstance(task_id, bool) or not isinstance(task_id, int) or task_id < 1:
        raise ToolError("task_id must be a positive integer.")

    try:
        task = _visible_tasks(user).get(pk=task_id)
    except Task.DoesNotExist as exc:
        raise ToolError("Task not found.") from exc
    if not task.can_view(user):
        raise ToolError("Task not found.")
    return task


def _serialize_task(task: Task) -> TaskRecord:
    return {
        "id": task.pk,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "status_display": task.get_status_display(),
        "priority": task.priority,
        "priority_display": task.get_priority_display(),
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "due_status": task.due_status,
        "is_overdue": task.is_overdue,
        "created_by": task.created_by.username if task.created_by else None,
        "assigned_to": task.assigned_to.username if task.assigned_to else None,
        "project": task.project.name if task.project else None,
        "labels": [
            {"name": label.name, "color": label.color}
            for label in task.labels.all()
        ],
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
    }


def _validate_limit(limit: int) -> None:
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_TASK_LIST_LIMIT
    ):
        raise ToolError(f"limit must be between 1 and {MAX_TASK_LIST_LIMIT}.")


def _validate_status(status: str | None) -> str | None:
    if status is not None and status not in dict(Task.STATUS_CHOICES):
        choices = ", ".join(value for value, _ in Task.STATUS_CHOICES)
        raise ToolError(f"status must be one of: {choices}.")
    return status


def _form_error_message(form: TaskForm) -> str:
    errors = []
    for field_name, field_errors in form.errors.items():
        label = "task" if field_name == "__all__" else field_name.replace("_", " ")
        errors.append(f"{label}: {', '.join(str(error) for error in field_errors)}")
    return "Invalid task data: " + "; ".join(errors)


def _task_from_form(form: TaskForm, actor: User) -> Task:
    task = form.save(commit=False)
    task.created_by = actor
    with transaction.atomic():
        task.save()
        form.save_m2m()
        TaskActivityLog.objects.create(
            task=task,
            actor=actor,
            action="CREATED",
            details=f"Task '{task.title}' created via MCP.",
        )
        if task.assigned_to and task.assigned_to != actor:
            create_notification(
                recipient=task.assigned_to,
                actor=actor,
                verb=f"assigned you to task '{task.title}'",
                task=task,
                notification_type=Notification.TYPE_ASSIGNMENT,
            )
    return task


def list_my_tasks(status: str | None = None, limit: int = 50) -> TaskListResult:
    """List tasks assigned to the configured TaskFlow user."""
    user = _get_active_user()
    _validate_limit(limit)
    status = _validate_status(status)

    tasks = Task.objects.filter(assigned_to=user).select_related(
        "created_by", "assigned_to", "project"
    ).prefetch_related("labels", "checklist_items")
    if status:
        tasks = tasks.filter(status=status)
    result = [_serialize_task(task) for task in tasks.order_by("-created_at")[:limit]]
    return {"count": len(result), "tasks": result}


def get_task_details(task_id: int) -> TaskDetails:
    """Get a visible task and its recent activity and comments."""
    user = _get_active_user()
    task = _get_visible_task(user, task_id)
    activity = [
        {
            "action": item.action,
            "details": item.details,
            "actor": item.actor.username if item.actor else None,
            "timestamp": item.timestamp.isoformat(),
        }
        for item in task.activity_logs.select_related("actor")[:20]
    ]
    comments = [
        {
            "id": item.pk,
            "author": item.author.username,
            "content": item.content,
            "created_at": item.created_at.isoformat(),
        }
        for item in task.comments.select_related("author").order_by("-created_at")[:20]
    ]
    checklist_items = [
        {
            "id": item.pk,
            "title": item.title,
            "position": item.position,
            "is_completed": item.is_completed,
        }
        for item in task.checklist_items.all()
    ]
    return {
        **_serialize_task(task),
        "activity": activity,
        "comments": comments,
        "checklist_items": checklist_items,
    }


def list_overdue_tasks(limit: int = 50) -> TaskListResult:
    """List overdue, incomplete tasks visible to the configured user."""
    user = _get_active_user()
    _validate_limit(limit)
    tasks = _visible_tasks(user).filter(
        due_date__lt=timezone.localdate(),
    ).exclude(status=Task.STATUS_COMPLETED)
    result = [_serialize_task(task) for task in tasks.order_by("due_date", "-created_at")[:limit]]
    return {"count": len(result), "tasks": result}


def get_task_summary() -> TaskSummary:
    """Summarize tasks in the configured user's permitted scope."""
    user = _get_active_user()
    tasks = _visible_tasks(user)
    total = tasks.count()
    completed = tasks.filter(status=Task.STATUS_COMPLETED).count()
    in_progress = tasks.filter(status=Task.STATUS_IN_PROGRESS).count()
    todo = tasks.filter(status=Task.STATUS_TODO).count()
    overdue = tasks.filter(
        due_date__lt=timezone.localdate(),
        status__in=[Task.STATUS_TODO, Task.STATUS_IN_PROGRESS],
    ).count()
    return {
        "scope": "all_tasks" if user.is_admin_role else "assigned_to_me",
        "total": total,
        "completed": completed,
        "in_progress": in_progress,
        "todo": todo,
        "overdue": overdue,
        "completion_rate": round(completed / total * 100, 1) if total else 0.0,
    }


def create_task(
    title: str,
    description: str = "",
    status: str = Task.STATUS_TODO,
    priority: str = Task.PRIORITY_MEDIUM,
    due_date: str | None = None,
    assignee_username: str | None = None,
) -> TaskMutationResult:
    """Create a task as an administrator, using TaskForm validation."""
    actor = _get_active_user()
    if not actor.is_admin_role:
        raise ToolError("Only administrators can create tasks.")
    if len(description) > MAX_TASK_DESCRIPTION_LENGTH:
        raise ToolError(
            f"description must be {MAX_TASK_DESCRIPTION_LENGTH} characters or fewer."
        )

    parsed_due_date = None
    if due_date:
        try:
            parsed_due_date = date.fromisoformat(due_date)
        except ValueError as exc:
            raise ToolError("due_date must be a valid ISO date in YYYY-MM-DD format.") from exc
        if parsed_due_date.isoformat() != due_date:
            raise ToolError("due_date must be a valid ISO date in YYYY-MM-DD format.")

    assigned_to_id = ""
    if assignee_username:
        try:
            assignee = User.objects.get(username=assignee_username, is_active=True)
        except User.DoesNotExist as exc:
            raise ToolError("Assignee must be an active TaskFlow user.") from exc
        assigned_to_id = str(assignee.pk)

    form = TaskForm(data={
        "title": title,
        "description": description,
        "status": status,
        "priority": priority,
        "due_date": parsed_due_date,
        "assigned_to": assigned_to_id,
    })
    if not form.is_valid():
        raise ToolError(_form_error_message(form))

    task = _task_from_form(form, actor)
    return {"task": _serialize_task(task), "changed": True}


def update_task_status(task_id: int, status: str) -> TaskMutationResult:
    """Update only a visible task's status; members may update assigned tasks."""
    actor = _get_active_user()
    task = _get_visible_task(actor, task_id)
    serializer = TaskStatusUpdateSerializer(data={"status": status})
    try:
        serializer.is_valid(raise_exception=True)
    except serializers.ValidationError as exc:
        errors = exc.detail.get("status", ["Invalid status."])
        raise ToolError(str(errors[0])) from exc

    new_status = serializer.validated_data["status"]
    old_status = task.status
    changed = old_status != new_status
    if changed:
        if not task.can_update_status(actor):
            raise ToolError("You may not update this task's status.")
        task.status = new_status
        with transaction.atomic():
            task.save()
            TaskActivityLog.objects.create(
                task=task,
                actor=actor,
                action="STATUS_CHANGE",
                details=f"Moved status from {old_status} to {new_status}",
            )
            target = task.created_by if actor == task.assigned_to else task.assigned_to
            if target:
                create_notification(
                    recipient=target,
                    actor=actor,
                    verb=f"moved '{task.title}' to {task.get_status_display()}",
                    task=task,
                    notification_type=Notification.TYPE_STATUS_CHANGE,
                )
    return {"task": _serialize_task(task), "changed": changed}


def assign_task(task_id: int, assignee_username: str) -> TaskMutationResult:
    """Assign a visible task to an active user; administrators only."""
    actor = _get_active_user()
    if not actor.is_admin_role:
        raise ToolError("Only administrators can assign tasks.")

    task = _get_visible_task(actor, task_id)
    try:
        assignee = User.objects.get(username=assignee_username, is_active=True)
    except User.DoesNotExist as exc:
        raise ToolError("Assignee must be an active TaskFlow user.") from exc

    old_assignee = task.assigned_to
    changed = old_assignee != assignee
    if changed:
        task.assigned_to = assignee
        with transaction.atomic():
            task.save()
            TaskActivityLog.objects.create(
                task=task,
                actor=actor,
                action="UPDATED",
                details=f"Reassigned to {assignee.display_name}",
            )
            create_notification(
                recipient=assignee,
                actor=actor,
                verb=f"assigned you to task '{task.title}'",
                task=task,
                notification_type=Notification.TYPE_ASSIGNMENT,
            )
    return {"task": _serialize_task(task), "changed": changed}
