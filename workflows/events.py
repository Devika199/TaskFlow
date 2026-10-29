import logging
from tasks.models import Task
from .engine import execute_workflow_rule
from .models import WorkflowExecution, WorkflowRule

logger = logging.getLogger(__name__)


def dispatch_task_event(
    event_type: str,
    task: Task,
    actor=None,
    previous_state: dict | None = None,
    event_id: str | None = None,
) -> list[WorkflowExecution]:
    """
    Centralized event dispatcher for all TaskFlow task lifecycle events.
    Queries and executes all enabled workflow rules for the task's organization.
    """
    if not task or not getattr(task, 'organization_id', None):
        return []

    rules = list(
        WorkflowRule.objects.filter(
            organization_id=task.organization_id,
            trigger_type=event_type,
            is_enabled=True,
        ).order_by('id')
    )

    if not rules:
        return []

    executions = []
    for rule in rules:
        try:
            execution = execute_workflow_rule(
                rule=rule,
                task=task,
                event_type=event_type,
                actor=actor,
                event_id=event_id,
                extra_context=previous_state,
            )
            if execution:
                executions.append(execution)
        except Exception as exc:
            logger.exception(f"Unexpected error executing workflow rule {rule.id}: {exc}")

    return executions


def notify_task_created(task: Task, actor=None, event_id: str | None = None) -> list[WorkflowExecution]:
    """Dispatches events when a new task is created."""
    executions = []
    executions.extend(dispatch_task_event(WorkflowRule.TRIGGER_TASK_CREATED, task, actor=actor, event_id=event_id))

    if task.assigned_to_id:
        assign_event_id = f"{event_id}:assign" if event_id else None
        executions.extend(dispatch_task_event(WorkflowRule.TRIGGER_TASK_ASSIGNED, task, actor=actor, event_id=assign_event_id))

    if task.status == Task.STATUS_COMPLETED:
        comp_event_id = f"{event_id}:complete" if event_id else None
        executions.extend(dispatch_task_event(WorkflowRule.TRIGGER_TASK_COMPLETED, task, actor=actor, event_id=comp_event_id))

    return executions


def notify_task_status_changed(task: Task, actor=None, old_status: str | None = None, event_id: str | None = None) -> list[WorkflowExecution]:
    """Dispatches events when a task's status changes."""
    executions = []
    if old_status and old_status == task.status:
        return executions

    executions.extend(
        dispatch_task_event(
            WorkflowRule.TRIGGER_TASK_STATUS_CHANGED,
            task,
            actor=actor,
            previous_state={'old_status': old_status},
            event_id=event_id,
        )
    )

    if task.status == Task.STATUS_COMPLETED:
        comp_event_id = f"{event_id}:complete" if event_id else None
        executions.extend(
            dispatch_task_event(
                WorkflowRule.TRIGGER_TASK_COMPLETED,
                task,
                actor=actor,
                previous_state={'old_status': old_status},
                event_id=comp_event_id,
            )
        )

    return executions


def notify_task_assigned(task: Task, actor=None, old_assignee=None, event_id: str | None = None) -> list[WorkflowExecution]:
    """Dispatches events when a task is assigned or reassigned."""
    return dispatch_task_event(
        WorkflowRule.TRIGGER_TASK_ASSIGNED,
        task,
        actor=actor,
        previous_state={'old_assignee': old_assignee},
        event_id=event_id,
    )


def notify_task_updated(
    task: Task,
    actor=None,
    old_status: str | None = None,
    old_assignee=None,
    event_id: str | None = None,
) -> list[WorkflowExecution]:
    """Dispatches events when a task is updated with possible status and/or assignee changes."""
    executions = []
    if old_status is not None and old_status != task.status:
        status_event_id = f"{event_id}:status" if event_id else None
        executions.extend(notify_task_status_changed(task, actor=actor, old_status=old_status, event_id=status_event_id))

    if old_assignee is not None and old_assignee != task.assigned_to:
        assign_event_id = f"{event_id}:assign" if event_id else None
        executions.extend(notify_task_assigned(task, actor=actor, old_assignee=old_assignee, event_id=assign_event_id))

    return executions

