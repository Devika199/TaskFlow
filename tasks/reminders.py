import logging
from datetime import date, timedelta
from django.db import transaction
from django.utils import timezone
from notifications.models import Notification
from notifications.services import create_notification
from organizations.models import OrganizationMembership
from .models import Task, TaskActivityLog, TaskReminderLog

logger = logging.getLogger(__name__)


def generate_reminder_idempotency_key(task_id: int, reminder_type: str, target_due_date: date) -> str:
    """Creates a deterministic, unique key for a task reminder period."""
    return f"reminder:{task_id}:{reminder_type}:{target_due_date.isoformat()}"


def is_task_eligible_for_reminder(task: Task) -> tuple[bool, str]:
    """
    Evaluates whether a task and its assignee qualify for an automated reminder.
    Verifies task status, due date presence, assignee presence, and organization membership.
    """
    if not task:
        return False, "Task does not exist"

    if task.status == Task.STATUS_COMPLETED:
        return False, "Task is completed"

    if not task.due_date:
        return False, "Task has no due date"

    if not task.assigned_to_id:
        return False, "Task has no assignee"

    if not task.assigned_to.is_active:
        return False, "Assignee account is inactive"

    if task.organization_id:
        is_member = OrganizationMembership.objects.filter(
            organization_id=task.organization_id,
            user_id=task.assigned_to_id,
            is_active=True,
        ).exists()
        if not is_member:
            return False, "Assignee is not an active member of the task organization"

    return True, "Eligible"


def process_task_reminder(
    task: Task,
    reminder_type: str,
    reference_date: date | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Processes a single reminder for an eligible task with atomic transaction safeguards
    and database-level duplicate prevention.
    """
    today = reference_date or timezone.localdate()
    eligible, reason = is_task_eligible_for_reminder(task)

    if not eligible:
        return {
            'status': 'SKIPPED',
            'task_id': task.id,
            'reminder_type': reminder_type,
            'reason': reason,
        }

    target_due_date = task.due_date
    idempotency_key = generate_reminder_idempotency_key(task.id, reminder_type, target_due_date)

    # Check if a reminder for this exact task, type, and due-date period was already sent
    already_sent = TaskReminderLog.objects.filter(
        idempotency_key=idempotency_key,
        status=TaskReminderLog.STATUS_SENT,
    ).exists()

    if already_sent:
        return {
            'status': 'ALREADY_SENT',
            'task_id': task.id,
            'reminder_type': reminder_type,
            'target_due_date': target_due_date.isoformat(),
        }

    if dry_run:
        return {
            'status': 'WOULD_SEND',
            'task_id': task.id,
            'reminder_type': reminder_type,
            'recipient': task.assigned_to.username,
            'target_due_date': target_due_date.isoformat(),
        }

    with transaction.atomic():
        try:
            reminder_log, created = TaskReminderLog.objects.get_or_create(
                idempotency_key=idempotency_key,
                defaults={
                    'organization': task.organization,
                    'task': task,
                    'recipient': task.assigned_to,
                    'reminder_type': reminder_type,
                    'target_due_date': target_due_date,
                    'status': TaskReminderLog.STATUS_PENDING,
                }
            )
        except Exception:
            # Concurrent race caught by database unique constraint
            reminder_log = TaskReminderLog.objects.filter(idempotency_key=idempotency_key).first()
            if not reminder_log:
                return {'status': 'FAILED', 'task_id': task.id, 'error': 'Could not register reminder log'}
            created = False

        if not created and reminder_log.status == TaskReminderLog.STATUS_SENT:
            return {
                'status': 'ALREADY_SENT',
                'task_id': task.id,
                'reminder_type': reminder_type,
                'target_due_date': target_due_date.isoformat(),
            }

        try:
            # Build friendly notification message
            if reminder_type == TaskReminderLog.REMINDER_DUE_SOON:
                if target_due_date == today:
                    verb = f"Reminder: Task '{task.title}' is due today ({target_due_date.isoformat()})."
                else:
                    verb = f"Reminder: Task '{task.title}' is due soon on {target_due_date.isoformat()}."
            else:
                days_overdue = (today - target_due_date).days
                day_word = "day" if days_overdue == 1 else "days"
                verb = f"Overdue Alert: Task '{task.title}' was due on {target_due_date.isoformat()} ({days_overdue} {day_word} ago)."

            # Double-defense duplicate prevention: skip if identical unread notification exists
            existing_notif = Notification.objects.filter(
                organization=task.organization,
                recipient=task.assigned_to,
                task=task,
                verb=verb[:255],
                is_read=False,
            ).first()

            if existing_notif:
                notif = existing_notif
            else:
                notif = create_notification(
                    recipient=task.assigned_to,
                    actor=None,
                    verb=verb[:255],
                    task=task,
                    notification_type=Notification.TYPE_SYSTEM,
                )

            # Record in TaskActivityLog for visible task audit trail
            TaskActivityLog.objects.create(
                task=task,
                actor=None,
                action='REMINDER',
                details=f"Automated {reminder_type.lower()} reminder dispatched to @{task.assigned_to.username}."
            )

            reminder_log.status = TaskReminderLog.STATUS_SENT
            reminder_log.sent_at = timezone.now()
            reminder_log.notification = notif
            reminder_log.error_summary = ''
            reminder_log.save(update_fields=['status', 'sent_at', 'notification', 'error_summary'])

            return {
                'status': 'SENT',
                'task_id': task.id,
                'reminder_type': reminder_type,
                'recipient': task.assigned_to.username,
                'target_due_date': target_due_date.isoformat(),
            }

        except Exception as exc:
            logger.exception(f"Failed to process reminder for task {task.id}: {exc}")
            reminder_log.status = TaskReminderLog.STATUS_FAILED
            reminder_log.error_summary = str(exc)[:500]
            reminder_log.save(update_fields=['status', 'error_summary'])
            return {
                'status': 'FAILED',
                'task_id': task.id,
                'reminder_type': reminder_type,
                'error': str(exc)[:200],
            }


def process_task_reminders_batch(
    organization=None,
    days_ahead: int = 1,
    batch_size: int = 100,
    dry_run: bool = False,
    reference_date: date | None = None,
) -> dict:
    """
    Scans for upcoming and overdue tasks across organizations, processing reminders
    in bounded batches with per-task fault isolation.
    """
    today = reference_date or timezone.localdate()
    window_end = today + timedelta(days=days_ahead)

    base_qs = Task.objects.select_related('organization', 'assigned_to').filter(
        status__in=[Task.STATUS_TODO, Task.STATUS_IN_PROGRESS],
        due_date__isnull=False,
    )
    if organization:
        base_qs = base_qs.filter(organization=organization)

    # 1. Upcoming tasks: due between today and window_end
    due_soon_tasks = list(
        base_qs.filter(
            due_date__gte=today,
            due_date__lte=window_end,
        ).order_by('due_date', 'id')[:batch_size]
    )

    # 2. Overdue tasks: due before today
    overdue_tasks = list(
        base_qs.filter(
            due_date__lt=today,
        ).order_by('due_date', 'id')[:batch_size]
    )

    summary = {
        'processed': 0,
        'sent': 0,
        'skipped': 0,
        'already_sent': 0,
        'failed': 0,
        'would_send': 0,
        'details': [],
    }

    # Process due soon reminders
    for task in due_soon_tasks:
        summary['processed'] += 1
        try:
            res = process_task_reminder(
                task=task,
                reminder_type=TaskReminderLog.REMINDER_DUE_SOON,
                reference_date=today,
                dry_run=dry_run,
            )
            summary['details'].append(res)
            st = res.get('status')
            if st == 'SENT':
                summary['sent'] += 1
            elif st == 'WOULD_SEND':
                summary['would_send'] += 1
            elif st == 'ALREADY_SENT':
                summary['already_sent'] += 1
            elif st == 'SKIPPED':
                summary['skipped'] += 1
            elif st == 'FAILED':
                summary['failed'] += 1
        except Exception as exc:
            summary['failed'] += 1
            summary['details'].append({'status': 'FAILED', 'task_id': task.id, 'error': str(exc)[:200]})

    # Process overdue reminders
    for task in overdue_tasks:
        summary['processed'] += 1
        try:
            res = process_task_reminder(
                task=task,
                reminder_type=TaskReminderLog.REMINDER_OVERDUE,
                reference_date=today,
                dry_run=dry_run,
            )
            summary['details'].append(res)
            st = res.get('status')
            if st == 'SENT':
                summary['sent'] += 1
            elif st == 'WOULD_SEND':
                summary['would_send'] += 1
            elif st == 'ALREADY_SENT':
                summary['already_sent'] += 1
            elif st == 'SKIPPED':
                summary['skipped'] += 1
            elif st == 'FAILED':
                summary['failed'] += 1
        except Exception as exc:
            summary['failed'] += 1
            summary['details'].append({'status': 'FAILED', 'task_id': task.id, 'error': str(exc)[:200]})

    return summary

