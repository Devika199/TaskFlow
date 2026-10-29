from django import forms
from django.core.exceptions import ValidationError
from tasks.models import Label, Project, Task
from .conditions import validate_rule_conditions
from .actions import validate_rule_actions
from .models import WorkflowRule


class WorkflowRuleForm(forms.ModelForm):
    # Friendly UI condition fields
    condition_status = forms.ChoiceField(
        choices=[('', 'Any Status')] + list(Task.STATUS_CHOICES),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label="Status Filter"
    )
    condition_priority = forms.ChoiceField(
        choices=[('', 'Any Priority')] + list(Task.PRIORITY_CHOICES),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label="Priority Filter"
    )
    condition_project = forms.ModelChoiceField(
        queryset=Project.objects.none(),
        required=False,
        empty_label="Any Project",
        widget=forms.Select(attrs={'class': 'form-select'}),
        label="Project Filter"
    )
    condition_assignee = forms.ChoiceField(
        choices=[
            ('', 'Any Assignee State'),
            ('assigned', 'Must be Assigned'),
            ('unassigned', 'Must be Unassigned'),
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label="Assignee Filter"
    )

    # Friendly UI action fields
    action_type = forms.ChoiceField(
        choices=[
            ('CREATE_NOTIFICATION', 'Send In-App Notification'),
            ('LOG_AUDIT', 'Record Audit Log Entry'),
            ('UPDATE_TASK_FIELD', 'Update Task Status/Priority'),
        ],
        widget=forms.Select(attrs={'class': 'form-select'}),
        label="Primary Action"
    )
    action_recipient = forms.ChoiceField(
        choices=[
            ('assignee', 'Notify Task Assignee'),
            ('creator', 'Notify Task Creator'),
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label="Notification Recipient"
    )
    action_message = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': "e.g. Automated alert: Task '{title}' requires attention.",
        }),
        label="Custom Notification Message"
    )
    action_target_status = forms.ChoiceField(
        choices=[('', 'Select Target Status')] + list(Task.STATUS_CHOICES),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label="Set Task Status To"
    )
    action_target_priority = forms.ChoiceField(
        choices=[('', 'Select Target Priority')] + list(Task.PRIORITY_CHOICES),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label="Set Task Priority To"
    )

    class Meta:
        model = WorkflowRule
        fields = ['name', 'description', 'trigger_type', 'is_enabled']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Auto-Notify On Critical Tasks'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Brief description of when and why this rule runs...'}),
            'trigger_type': forms.Select(attrs={'class': 'form-select'}),
            'is_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization or (self.instance.organization if self.instance.pk else None)

        if self.organization:
            self.fields['condition_project'].queryset = Project.objects.filter(
                organization=self.organization,
                archived=False
            ).order_by('name')

        # Populate initial values when editing existing rule
        if self.instance and self.instance.pk:
            conds = self.instance.conditions or {}
            if 'status' in conds and conds['status'].get('operator') == 'equals':
                self.fields['condition_status'].initial = conds['status'].get('value')
            if 'priority' in conds and conds['priority'].get('operator') == 'equals':
                self.fields['condition_priority'].initial = conds['priority'].get('value')
            if 'project' in conds and conds['project'].get('operator') == 'equals':
                self.fields['condition_project'].initial = conds['project'].get('value')
            if 'assignee' in conds:
                op = conds['assignee'].get('operator')
                if op in ('assigned', 'unassigned'):
                    self.fields['condition_assignee'].initial = op

            actions = self.instance.actions or []
            if actions:
                first_action = actions[0]
                a_type = first_action.get('action_type')
                self.fields['action_type'].initial = a_type
                if a_type == 'CREATE_NOTIFICATION':
                    self.fields['action_recipient'].initial = first_action.get('recipient')
                    self.fields['action_message'].initial = first_action.get('message', '')
                elif a_type == 'UPDATE_TASK_FIELD':
                    f = first_action.get('field')
                    if f == 'status':
                        self.fields['action_target_status'].initial = first_action.get('value')
                    elif f == 'priority':
                        self.fields['action_target_priority'].initial = first_action.get('value')

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        qs = WorkflowRule.objects.filter(name__iexact=name)
        if self.organization:
            qs = qs.filter(organization=self.organization)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("A workflow rule with this name already exists in your organization.")
        return name

    def clean(self):
        cleaned_data = super().clean()
        conditions = {}

        status_val = cleaned_data.get('condition_status')
        if status_val:
            conditions['status'] = {'operator': 'equals', 'value': status_val}

        priority_val = cleaned_data.get('condition_priority')
        if priority_val:
            conditions['priority'] = {'operator': 'equals', 'value': priority_val}

        project_obj = cleaned_data.get('condition_project')
        if project_obj:
            conditions['project'] = {'operator': 'equals', 'value': project_obj.id}

        assignee_val = cleaned_data.get('condition_assignee')
        if assignee_val in ('assigned', 'unassigned'):
            conditions['assignee'] = {'operator': assignee_val, 'value': True}

        validate_rule_conditions(conditions, organization=self.organization)

        # Build actions
        a_type = cleaned_data.get('action_type')
        actions = []

        if a_type == 'CREATE_NOTIFICATION':
            recipient = cleaned_data.get('action_recipient') or 'assignee'
            msg = cleaned_data.get('action_message', '').strip()
            actions.append({
                'action_type': 'CREATE_NOTIFICATION',
                'recipient': recipient,
                'message': msg or "Workflow rule triggered for task '{title}'.",
            })
        elif a_type == 'LOG_AUDIT':
            actions.append({
                'action_type': 'LOG_AUDIT',
                'details': f"Workflow '{cleaned_data.get('name')}' triggered and executed.",
            })
        elif a_type == 'UPDATE_TASK_FIELD':
            target_status = cleaned_data.get('action_target_status')
            target_priority = cleaned_data.get('action_target_priority')

            if target_status:
                actions.append({
                    'action_type': 'UPDATE_TASK_FIELD',
                    'field': 'status',
                    'value': target_status,
                })
            elif target_priority:
                actions.append({
                    'action_type': 'UPDATE_TASK_FIELD',
                    'field': 'priority',
                    'value': target_priority,
                })
            else:
                self.add_error('action_target_status', "Please choose a target status or target priority to update.")

        validate_rule_actions(actions, organization=self.organization)

        self.instance.conditions = conditions
        self.instance.actions = actions
        return cleaned_data

    def save(self, commit=True):
        rule = super().save(commit=False)
        if self.organization and not rule.organization_id:
            rule.organization = self.organization
        if commit:
            rule.save()
        return rule

