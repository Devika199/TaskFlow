from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from .forms import WorkflowRuleForm
from .models import WorkflowExecution, WorkflowRule


def _check_org_admin(request):
    org = getattr(request, 'organization', None)
    if not org:
        raise PermissionDenied("An active organization is required to manage workflows.")
    membership = getattr(request, 'membership', None)
    is_admin = (membership and membership.is_admin) or request.user.is_admin_role
    if not is_admin:
        raise PermissionDenied("Only organization administrators can manage workflows.")


@login_required
def rule_list_view(request):
    """Lists all workflow rules for the active organization."""
    _check_org_admin(request)
    org = getattr(request, 'organization', None)

    rules = WorkflowRule.objects.filter(organization=org).select_related('created_by')
    total_executions = WorkflowExecution.objects.filter(organization=org).count()
    successful_executions = WorkflowExecution.objects.filter(
        organization=org, status=WorkflowExecution.STATUS_SUCCESS
    ).count()

    return render(request, 'workflows/rule_list.html', {
        'rules': rules,
        'total_executions': total_executions,
        'successful_executions': successful_executions,
    })


@login_required
def rule_create_view(request):
    """Creates a new workflow rule in the active organization."""
    _check_org_admin(request)
    org = getattr(request, 'organization', None)

    if request.method == 'POST':
        form = WorkflowRuleForm(request.POST, organization=org)
        if form.is_valid():
            rule = form.save(commit=False)
            rule.organization = org
            rule.created_by = request.user
            rule.save()
            messages.success(request, f"Workflow rule '{rule.name}' created successfully.")
            return redirect('workflow_rule_list')
        else:
            messages.error(request, "Please correct the errors in the rule configuration.")
    else:
        form = WorkflowRuleForm(organization=org)

    return render(request, 'workflows/rule_form.html', {
        'form': form,
        'title': 'Create Automation Rule',
        'action_label': 'Create Rule',
    })


@login_required
def rule_edit_view(request, pk):
    """Edits an existing workflow rule within the active organization."""
    _check_org_admin(request)
    org = getattr(request, 'organization', None)
    rule = get_object_or_404(WorkflowRule, pk=pk, organization=org)

    if request.method == 'POST':
        form = WorkflowRuleForm(request.POST, instance=rule, organization=org)
        if form.is_valid():
            form.save()
            messages.success(request, f"Workflow rule '{rule.name}' updated successfully.")
            return redirect('workflow_rule_list')
        else:
            messages.error(request, "Please fix the errors below.")
    else:
        form = WorkflowRuleForm(instance=rule, organization=org)

    return render(request, 'workflows/rule_form.html', {
        'form': form,
        'rule': rule,
        'title': f'Edit Rule: {rule.name}',
        'action_label': 'Save Changes',
    })


@login_required
@require_POST
def rule_toggle_view(request, pk):
    """Toggles the enabled status of a workflow rule."""
    _check_org_admin(request)
    org = getattr(request, 'organization', None)
    rule = get_object_or_404(WorkflowRule, pk=pk, organization=org)

    rule.is_enabled = not rule.is_enabled
    rule.save(update_fields=['is_enabled', 'updated_at'])

    status_str = "enabled" if rule.is_enabled else "disabled"
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'is_enabled': rule.is_enabled, 'message': f"Rule '{rule.name}' {status_str}."})

    messages.success(request, f"Workflow rule '{rule.name}' has been {status_str}.")
    return redirect('workflow_rule_list')


@login_required
@require_POST
def rule_delete_view(request, pk):
    """Permanently deletes a workflow rule."""
    _check_org_admin(request)
    org = getattr(request, 'organization', None)
    rule = get_object_or_404(WorkflowRule, pk=pk, organization=org)

    rule_name = rule.name
    rule.delete()
    messages.success(request, f"Workflow rule '{rule_name}' was deleted.")
    return redirect('workflow_rule_list')


@login_required
def rule_history_view(request, pk):
    """Displays execution history and failure logs for a specific rule."""
    _check_org_admin(request)
    org = getattr(request, 'organization', None)
    rule = get_object_or_404(WorkflowRule, pk=pk, organization=org)

    executions = rule.executions.select_related('task').order_by('-created_at')[:100]
    return render(request, 'workflows/rule_history.html', {
        'rule': rule,
        'executions': executions,
    })


@login_required
def all_history_view(request):
    """Displays execution audit logs for all rules in the active organization."""
    _check_org_admin(request)
    org = getattr(request, 'organization', None)

    executions = WorkflowExecution.objects.filter(
        organization=org
    ).select_related('rule', 'task').order_by('-created_at')[:150]

    return render(request, 'workflows/rule_history.html', {
        'rule': None,
        'executions': executions,
    })
