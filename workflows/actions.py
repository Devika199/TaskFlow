from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from notifications.models import Notification
from tasks.models import Task, TaskActivityLog

User = get_user_model()

ALLOWED_ACTION_TYPES = {'CREATE_NOTIFICATION', 'LOG_AUDIT', 'UPDATE_TASK_FIELD'}
ALLOWED_SAFE_UPDATE_FIELDS = {'status', 'priority'}


def validate_rule_actions(actions: list, organization=None) -> None:
    """
    Validates the structure, types, and cross-tenant constraints of workflow actions.
    Raises ValidationError if any action definition is invalid.
    """
    if not isinstance(actions, list):
        raise ValidationError("Actions must be a list of action objects.")
    if len(actions) == 0:
        raise ValidationError("At least one action must be configured for the workflow rule.")

    for idx, action in enumerate(actions):
        if not isinstance(action, dict):
            raise ValidationError(f"Action at index {idx} must be a dictionary.")

        action_type = action.get('action_type')
        if action_type not in ALLOWED_ACTION_TYPES:
            raise ValidationError(
                f"Action {idx}: Unsupported action_type '{action_type}'. Allowed: {', '.join(sorted(ALLOWED_ACTION_TYPES))}"
            )

        if action_type == 'CREATE_NOTIFICATION':
            recipient_type = action.get('recipient')
            if recipient_type not in ('assignee', 'creator', 'specific_user'):
                raise ValidationError(
                    f"Action {idx} (CREATE_NOTIFICATION): 'recipient' must be one of: 'assignee', 'creator', 'specific_user'."
                )
            if recipient_type == 'specific_user':
                user_id = action.get('user_id')
                if not isinstance(user_id, int):
                    raise ValidationError(
                        f"Action {idx} (CREATE_NOTIFICATION): 'user_id' must be an integer when recipient is 'specific_user'."
                    )
                if organization:
                    from organizations.models import OrganizationMembership
                    if not OrganizationMembership.objects.filter(organization=organization, user_id=user_id, is_active=True).exists():
                        raise ValidationError(
                            f"Action {idx}: Recipient user ID {user_id} is not an active member of this organization."
                        )

            message = action.get('message')
            if message is not None and not isinstance(message, str):
                raise ValidationError(f"Action {idx} (CREATE_NOTIFICATION): 'message' must be a string.")

        elif action_type == 'LOG_AUDIT':
            details = action.get('details')
            if details is not None and not isinstance(details, str):
                raise ValidationError(f"Action {idx} (LOG_AUDIT): 'details' must be a string.")

        elif action_type == 'UPDATE_TASK_FIELD':
            field = action.get('field')
            value = action.get('value')
            if field not in ALLOWED_SAFE_UPDATE_FIELDS:
                raise ValidationError(
                    f"Action {idx} (UPDATE_TASK_FIELD): Safe update fields are restricted to: {', '.join(sorted(ALLOWED_SAFE_UPDATE_FIELDS))}."
                )

            if field == 'status':
                if value not in dict(Task.STATUS_CHOICES):
                    raise ValidationError(f"Action {idx}: Invalid status choice '{value}'.")
            elif field == 'priority':
                if value not in dict(Task.PRIORITY_CHOICES):
                    raise ValidationError(f"Action {idx}: Invalid priority choice '{value}'.")


def execute_action(action: dict, task: Task, rule, actor=None) -> dict:
    """
    Executes a single validated action deterministically and returns an execution report dict.
    Strictly tenant-scoped to task.organization.
    """
    action_type = action.get('action_type')

    if action_type == 'CREATE_NOTIFICATION':
        recipient_type = action.get('recipient')
        recipient = None

        if recipient_type == 'assignee':
            recipient = task.assigned_to
        elif recipient_type == 'creator':
            recipient = task.created_by
        elif recipient_type == 'specific_user':
            user_id = action.get('user_id')
            if user_id:
                recipient = User.objects.filter(
                    id=user_id,
                    organization_memberships__organization=task.organization,
                    organization_memberships__is_active=True
                ).first()

        if not recipient:
            return {
                'action_type': action_type,
                'status': 'SKIPPED',
                'details': f"No recipient found for type '{recipient_type}' within organization."
            }

        custom_message = action.get('message', '').strip()
        if not custom_message:
            custom_message = f"Workflow '{rule.name}' triggered for task '{task.title}'."
        else:
            # Safe basic interpolation
            custom_message = custom_message.replace('{title}', task.title)
            custom_message = custom_message.replace('{id}', str(task.id))
            custom_message = custom_message.replace('{rule_name}', rule.name)

        # Double defense: check if an identical unread notification already exists for this task & recipient
        existing_notif = Notification.objects.filter(
            organization=task.organization,
            recipient=recipient,
            task=task,
            verb=custom_message[:255],
            is_read=False,
        ).first()
        if existing_notif:
            return {
                'action_type': action_type,
                'status': 'SKIPPED',
                'details': f"Duplicate unread notification already exists (ID {existing_notif.id}).",
            }

        notification = Notification.objects.create(
            organization=task.organization,
            recipient=recipient,
            actor=actor or rule.created_by,
            verb=custom_message[:255],
            task=task,
            notification_type=Notification.TYPE_SYSTEM
        )
        return {
            'action_type': action_type,
            'status': 'SUCCESS',
            'details': f"Created notification ID {notification.id} for user {recipient.username}."
        }

    elif action_type == 'LOG_AUDIT':
        details = action.get('details', '').strip()
        if not details:
            details = f"Automated workflow '{rule.name}' executed."
        else:
            details = details.replace('{title}', task.title)
            details = details.replace('{rule_name}', rule.name)

        log = TaskActivityLog.objects.create(
            task=task,
            actor=actor or rule.created_by,
            action='UPDATED',
            details=details[:500]
        )
        return {
            'action_type': action_type,
            'status': 'SUCCESS',
            'details': f"Logged task activity audit ID {log.id}."
        }

    elif action_type == 'UPDATE_TASK_FIELD':
        field = action.get('field')
        value = action.get('value')

        if field not in ALLOWED_SAFE_UPDATE_FIELDS:
            return {
                'action_type': action_type,
                'status': 'FAILED',
                'details': f"Unsafe or unsupported field update: '{field}'.",
            }

        if field == 'status' and value not in dict(Task.STATUS_CHOICES):
            return {
                'action_type': action_type,
                'status': 'FAILED',
                'details': f"Invalid status choice '{value}'.",
            }
        if field == 'priority' and value not in dict(Task.PRIORITY_CHOICES):
            return {
                'action_type': action_type,
                'status': 'FAILED',
                'details': f"Invalid priority choice '{value}'.",
            }

        old_value = getattr(task, field)

        if old_value != value:
            setattr(task, field, value)
            # Update specific field without triggering unintended signal loops
            update_fields = [field, 'updated_at']
            if field == 'status' and value == Task.STATUS_COMPLETED:
                from django.utils import timezone
                task.completed_at = timezone.now()
                update_fields.append('completed_at')
            elif field == 'status' and old_value == Task.STATUS_COMPLETED:
                task.completed_at = None
                update_fields.append('completed_at')

            task.save(update_fields=update_fields)

            TaskActivityLog.objects.create(
                task=task,
                actor=actor or rule.created_by,
                action='STATUS_CHANGE' if field == 'status' else 'UPDATED',
                details=f"Workflow '{rule.name}' updated {field} from {old_value} to {value}."
            )
            return {
                'action_type': action_type,
                'status': 'SUCCESS',
                'details': f"Updated task {field} from {old_value} to {value}."
            }
        else:
            return {
                'action_type': action_type,
                'status': 'SKIPPED',
                'details': f"Task {field} already has value '{value}'."
            }

    return {
        'action_type': action_type,
        'status': 'FAILED',
        'details': f"Unknown action type '{action_type}'."
    }

