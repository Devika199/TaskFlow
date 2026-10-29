import logging
import threading
from django.db import IntegrityError, transaction
from django.utils import timezone
from .actions import execute_action
from .conditions import evaluate_conditions
from .models import WorkflowExecution, WorkflowRule

logger = logging.getLogger(__name__)

_THREAD_LOCALS = threading.local()
MAX_WORKFLOW_DEPTH = 3


def _get_workflow_depth() -> int:
    return getattr(_THREAD_LOCALS, 'workflow_depth', 0)


def _set_workflow_depth(depth: int) -> None:
    _THREAD_LOCALS.workflow_depth = depth


def execute_workflow_rule(
    rule: WorkflowRule,
    task,
    event_type: str,
    actor=None,
    event_id: str | None = None,
    extra_context: dict | None = None,
) -> WorkflowExecution | None:
    """
    Executes a single workflow rule against a task deterministically with idempotency
    and recursion depth protection.
    """
    # 1. Organization tenant boundary check
    if not task.organization_id or task.organization_id != rule.organization_id:
        logger.warning(
            f"Tenant mismatch: Rule {rule.id} (org {rule.organization_id}) cannot execute on task {task.id} (org {task.organization_id})"
        )
        return None

    # 2. Rule must be enabled
    if not rule.is_enabled:
        return None

    # 3. Recursion depth check (infinite loop protection)
    current_depth = _get_workflow_depth()
    if current_depth >= MAX_WORKFLOW_DEPTH:
        logger.warning(
            f"Workflow recursion depth limit ({MAX_WORKFLOW_DEPTH}) reached for rule {rule.id} on task {task.id}. Execution halted."
        )
        return None

    # 4. Generate database-enforced idempotency key
    # If caller provided explicit event_id, use it; otherwise use timestamp fingerprint
    event_token = event_id or f"{task.updated_at.isoformat() if task.updated_at else 'init'}"
    idempotency_key = f"rule_{rule.id}:{event_type}:task_{task.id}:{event_token}"

    # 5. Check or create execution record with race-condition safety
    try:
        with transaction.atomic():
            execution, created = WorkflowExecution.objects.get_or_create(
                idempotency_key=idempotency_key,
                defaults={
                    'organization': rule.organization,
                    'rule': rule,
                    'triggering_event': event_type,
                    'task': task,
                    'status': WorkflowExecution.STATUS_RUNNING,
                    'execution_log': {'init': 'Execution registered'},
                }
            )
    except (IntegrityError, Exception):
        # Concurrent request created it simultaneously or database locked
        execution = WorkflowExecution.objects.filter(idempotency_key=idempotency_key).first()
        if not execution:
            return None
        created = False

    if not created:
        # Already executed or currently running
        if execution.status in (WorkflowExecution.STATUS_SUCCESS, WorkflowExecution.STATUS_RUNNING, WorkflowExecution.STATUS_SKIPPED):
            logger.info(f"Duplicate event ignored for rule {rule.id} on task {task.id} (idempotency key: {idempotency_key})")
            return execution
        # If it failed previously, increment retry count and resume
        execution.retry_count += 1
        execution.status = WorkflowExecution.STATUS_RUNNING
        execution.save(update_fields=['retry_count', 'status'])

    # 6. Evaluate rule conditions
    matched, cond_logs = evaluate_conditions(rule.conditions, task)
    if not matched:
        execution.mark_completed(
            status=WorkflowExecution.STATUS_SKIPPED,
            log={'conditions_matched': False, 'logs': cond_logs},
            error_summary="Conditions not met"
        )
        return execution

    # 7. Execute actions inside depth context with transaction rollback on partial failure
    _set_workflow_depth(current_depth + 1)
    action_reports = []
    has_failure = False
    error_summary = ""

    try:
        with transaction.atomic():
            for action in rule.actions:
                report = execute_action(action, task, rule, actor=actor)
                action_reports.append(report)
                if report.get('status') == 'FAILED':
                    error_summary = report.get('details', 'Action failed.')
                    # Trigger rollback of all mutations made during this attempt
                    raise RuntimeError(error_summary)
    except Exception as exc:
        has_failure = True
        error_summary = f"Error during action execution: {str(exc)[:200]}"
        try:
            task.refresh_from_db()
        except Exception:
            pass

    # Save execution status outside the rolled-back action transaction
    if has_failure:
        execution.mark_completed(
            status=WorkflowExecution.STATUS_FAILED,
            log={'conditions_matched': True, 'actions': action_reports},
            error_summary=error_summary
        )
    else:
        execution.mark_completed(
            status=WorkflowExecution.STATUS_SUCCESS,
            log={'conditions_matched': True, 'actions': action_reports}
        )

    _set_workflow_depth(current_depth)
    return execution

