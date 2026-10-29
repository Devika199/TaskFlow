from datetime import date
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from tasks.models import Label, Project, Task

User = get_user_model()

ALLOWED_CONDITION_FIELDS = {'status', 'priority', 'project', 'labels', 'assignee', 'due_date'}


def validate_rule_conditions(conditions: dict, organization=None) -> None:
    """
    Strictly validates the structure, operators, and cross-tenant references of rule conditions.
    Raises ValidationError if any condition is invalid or unsupported.
    """
    if conditions is None:
        return
    if not isinstance(conditions, dict):
        raise ValidationError("Conditions must be a JSON object (dictionary).")

    for field, rule in conditions.items():
        if field not in ALLOWED_CONDITION_FIELDS:
            raise ValidationError(f"Unsupported condition field: '{field}'. Allowed: {', '.join(sorted(ALLOWED_CONDITION_FIELDS))}")

        if not isinstance(rule, dict):
            raise ValidationError(f"Condition for '{field}' must be a dictionary specifying operator and value.")

        operator = rule.get('operator')
        value = rule.get('value')

        if not operator or not isinstance(operator, str):
            raise ValidationError(f"Condition for '{field}' must specify a valid string 'operator'.")

        valid_statuses = set(dict(Task.STATUS_CHOICES).keys())
        valid_priorities = set(dict(Task.PRIORITY_CHOICES).keys())

        if field == 'status':
            if operator == 'equals':
                if value not in valid_statuses:
                    raise ValidationError(f"Invalid status value '{value}'. Choices: {sorted(valid_statuses)}")
            elif operator == 'in':
                if not isinstance(value, list) or not value or not all(v in valid_statuses for v in value):
                    raise ValidationError(f"Status 'in' operator requires a non-empty list of valid statuses.")
            else:
                raise ValidationError(f"Unsupported operator '{operator}' for status. Allowed: 'equals', 'in'.")

        elif field == 'priority':
            if operator == 'equals':
                if value not in valid_priorities:
                    raise ValidationError(f"Invalid priority value '{value}'. Choices: {sorted(valid_priorities)}")
            elif operator == 'in':
                if not isinstance(value, list) or not value or not all(v in valid_priorities for v in value):
                    raise ValidationError(f"Priority 'in' operator requires a non-empty list of valid priorities.")
            else:
                raise ValidationError(f"Unsupported operator '{operator}' for priority. Allowed: 'equals', 'in'.")

        elif field == 'project':
            if operator == 'equals':
                if value is not None and not isinstance(value, int):
                    raise ValidationError("Project 'equals' requires an integer project ID or null.")
                if organization and value is not None:
                    if not Project.objects.filter(id=value, organization=organization).exists():
                        raise ValidationError(f"Project ID {value} does not exist or does not belong to this organization.")
            elif operator == 'is_none':
                if not isinstance(value, bool):
                    raise ValidationError("Project 'is_none' operator requires a boolean value.")
            else:
                raise ValidationError(f"Unsupported operator '{operator}' for project. Allowed: 'equals', 'is_none'.")

        elif field == 'labels':
            if operator in ('contains', 'contains_any'):
                val_list = [value] if isinstance(value, int) else value
                if not isinstance(val_list, list) or not val_list or not all(isinstance(v, int) for v in val_list):
                    raise ValidationError(f"Labels '{operator}' operator requires an integer label ID or list of IDs.")
                if organization:
                    count = Label.objects.filter(id__in=val_list, organization=organization).count()
                    if count != len(set(val_list)):
                        raise ValidationError("One or more label IDs do not exist or do not belong to this organization.")
            elif operator == 'empty':
                if not isinstance(value, bool):
                    raise ValidationError("Labels 'empty' operator requires a boolean value.")
            else:
                raise ValidationError(f"Unsupported operator '{operator}' for labels. Allowed: 'contains', 'contains_any', 'empty'.")

        elif field == 'assignee':
            if operator in ('assigned', 'unassigned'):
                if not isinstance(value, bool):
                    raise ValidationError(f"Assignee '{operator}' operator requires a boolean value.")
            elif operator == 'equals':
                if not isinstance(value, int):
                    raise ValidationError("Assignee 'equals' operator requires an integer user ID.")
                if organization:
                    from organizations.models import OrganizationMembership
                    if not OrganizationMembership.objects.filter(organization=organization, user_id=value, is_active=True).exists():
                        raise ValidationError(f"User ID {value} is not an active member of this organization.")
            else:
                raise ValidationError(f"Unsupported operator '{operator}' for assignee. Allowed: 'assigned', 'unassigned', 'equals'.")

        elif field == 'due_date':
            if operator in ('is_set', 'is_not_set', 'overdue'):
                if not isinstance(value, bool):
                    raise ValidationError(f"Due date '{operator}' operator requires a boolean value.")
            else:
                raise ValidationError(f"Unsupported operator '{operator}' for due_date. Allowed: 'is_set', 'is_not_set', 'overdue'.")


def evaluate_conditions(conditions: dict, task: Task) -> tuple[bool, list[str]]:
    """
    Evaluates rule conditions against a task instance deterministically.
    Returns (is_matched: bool, logs: list[str]).
    """
    if not conditions:
        return True, ["No conditions specified (matches all)."]

    logs = []
    today = date.today()

    for field, rule in conditions.items():
        operator = rule.get('operator')
        target_val = rule.get('value')

        if field == 'status':
            actual_val = task.status
            if operator == 'equals':
                if actual_val != target_val:
                    logs.append(f"Condition failed: status '{actual_val}' != '{target_val}'")
                    return False, logs
            elif operator == 'in':
                if actual_val not in target_val:
                    logs.append(f"Condition failed: status '{actual_val}' not in {target_val}")
                    return False, logs

        elif field == 'priority':
            actual_val = task.priority
            if operator == 'equals':
                if actual_val != target_val:
                    logs.append(f"Condition failed: priority '{actual_val}' != '{target_val}'")
                    return False, logs
            elif operator == 'in':
                if actual_val not in target_val:
                    logs.append(f"Condition failed: priority '{actual_val}' not in {target_val}")
                    return False, logs

        elif field == 'project':
            actual_project_id = task.project_id
            if operator == 'equals':
                if actual_project_id != target_val:
                    logs.append(f"Condition failed: project ID '{actual_project_id}' != '{target_val}'")
                    return False, logs
            elif operator == 'is_none':
                is_none = (actual_project_id is None)
                if is_none != target_val:
                    logs.append(f"Condition failed: project is_none '{is_none}' != '{target_val}'")
                    return False, logs

        elif field == 'labels':
            actual_label_ids = set(task.labels.values_list('id', flat=True))
            if operator == 'contains':
                target_ids = {target_val} if isinstance(target_val, int) else set(target_val)
                if not target_ids.issubset(actual_label_ids):
                    logs.append(f"Condition failed: labels {actual_label_ids} does not contain all of {target_ids}")
                    return False, logs
            elif operator == 'contains_any':
                target_ids = {target_val} if isinstance(target_val, int) else set(target_val)
                if not target_ids.intersection(actual_label_ids):
                    logs.append(f"Condition failed: labels {actual_label_ids} does not contain any of {target_ids}")
                    return False, logs
            elif operator == 'empty':
                is_empty = (len(actual_label_ids) == 0)
                if is_empty != target_val:
                    logs.append(f"Condition failed: labels empty '{is_empty}' != '{target_val}'")
                    return False, logs

        elif field == 'assignee':
            if operator == 'assigned':
                is_assigned = (task.assigned_to_id is not None)
                if is_assigned != target_val:
                    logs.append(f"Condition failed: assignee assigned '{is_assigned}' != '{target_val}'")
                    return False, logs
            elif operator == 'unassigned':
                is_unassigned = (task.assigned_to_id is None)
                if is_unassigned != target_val:
                    logs.append(f"Condition failed: assignee unassigned '{is_unassigned}' != '{target_val}'")
                    return False, logs
            elif operator == 'equals':
                if task.assigned_to_id != target_val:
                    logs.append(f"Condition failed: assignee ID '{task.assigned_to_id}' != '{target_val}'")
                    return False, logs

        elif field == 'due_date':
            if operator == 'is_set':
                is_set = (task.due_date is not None)
                if is_set != target_val:
                    logs.append(f"Condition failed: due_date is_set '{is_set}' != '{target_val}'")
                    return False, logs
            elif operator == 'is_not_set':
                is_not_set = (task.due_date is None)
                if is_not_set != target_val:
                    logs.append(f"Condition failed: due_date is_not_set '{is_not_set}' != '{target_val}'")
                    return False, logs
            elif operator == 'overdue':
                is_overdue = bool(task.due_date and task.due_date < today and task.status != Task.STATUS_COMPLETED)
                if is_overdue != target_val:
                    logs.append(f"Condition failed: due_date overdue '{is_overdue}' != '{target_val}'")
                    return False, logs

    logs.append("All conditions successfully matched.")
    return True, logs

