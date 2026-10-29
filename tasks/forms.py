from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q
from .models import Label, Project, Task, TaskChecklistItem, TaskComment

User = get_user_model()


class ProjectModelChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        if getattr(obj, 'archived', False):
            return f"{obj.name} (Archived)"
        return obj.name


class TaskForm(forms.ModelForm):
    project = ProjectModelChoiceField(
        queryset=Project.objects.none(),
        required=False,
        empty_label="No Project (Optional)",
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    labels = forms.ModelMultipleChoiceField(
        queryset=Label.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={
            'class': 'form-select',
            'aria-describedby': 'labels-help',
            'size': '4',
        }),
    )

    class Meta:
        model = Task
        fields = ['title', 'description', 'status', 'priority', 'due_date', 'assigned_to', 'project', 'labels']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter clear, actionable task title...',
                'required': True
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Detailed context, requirements, acceptance criteria...'
            }),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'due_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'assigned_to': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, user=None, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        # Resolve organization
        if organization is not None:
            self.organization = organization
        elif self.instance and getattr(self.instance, 'organization_id', None):
            self.organization = self.instance.organization
        elif user and hasattr(user, 'organization_memberships'):
            mem = user.organization_memberships.filter(is_active=True).first()
            self.organization = mem.organization if mem else None
        else:
            self.organization = None

        # Filter assignees by organization membership
        if self.organization:
            assignees = User.objects.filter(
                Q(organization_memberships__organization=self.organization, organization_memberships__is_active=True)
                | Q(organization_memberships__isnull=True),
                is_active=True,
            ).distinct().order_by('first_name', 'username')
        else:
            assignees = User.objects.filter(is_active=True).order_by('first_name', 'username')
        self.fields['assigned_to'].queryset = assignees
        self.fields['assigned_to'].empty_label = "Unassigned"

        # Populate projects scoped to organization
        if self.organization:
            projects = Project.objects.filter(organization=self.organization, archived=False)
        else:
            projects = Project.objects.filter(archived=False)

        if user and not user.is_admin_role:
            projects = projects.filter(tasks__assigned_to=user).distinct()

        # Show currently selected project when editing, even if archived
        if self.instance and self.instance.pk and self.instance.project_id:
            projects = Project.objects.filter(Q(pk=self.instance.project_id) | Q(pk__in=projects))

        self.fields['project'].queryset = projects.order_by('name').distinct()
        self.fields['project'].required = False
        self.fields['project'].empty_label = "No Project (Optional)"

        # Populate labels scoped to organization
        if self.organization:
            self.fields['labels'].queryset = Label.objects.filter(organization=self.organization).order_by('name')
        else:
            self.fields['labels'].queryset = Label.objects.all().order_by('name')

    def clean(self):
        cleaned_data = super().clean()
        project = cleaned_data.get('project')
        labels = cleaned_data.get('labels')
        assigned_to = cleaned_data.get('assigned_to')

        if self.organization:
            if project and project.organization_id != self.organization.id:
                self.add_error('project', 'Selected project belongs to a different organization.')
            if labels:
                for label in labels:
                    if label.organization_id != self.organization.id:
                        self.add_error('labels', f"Label '{label.name}' belongs to a different organization.")
                        break
            if assigned_to:
                from .models import _get_user_org_cache
                active_ids, _, has_any = _get_user_org_cache(assigned_to)
                if has_any and self.organization.id not in active_ids:
                    self.add_error('assigned_to', 'Assignee is not an active member of this organization.')

        return cleaned_data

    def save(self, commit=True):
        task = super().save(commit=False)
        if self.organization and not task.organization_id:
            task.organization = self.organization
        if commit:
            task.save()
            self.save_m2m()
        return task


class TaskChecklistItemForm(forms.ModelForm):
    class Meta:
        model = TaskChecklistItem
        fields = ['title']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'maxlength': 255,
                'placeholder': 'Add a checklist item',
            }),
        }


class LabelForm(forms.ModelForm):
    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization is not None:
            self.organization = organization
        elif self.instance and getattr(self.instance, 'organization_id', None):
            self.organization = self.instance.organization
        else:
            self.organization = None

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        duplicates = Label.objects.filter(name__iexact=name)
        if self.organization:
            duplicates = duplicates.filter(organization=self.organization)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError('A label with this name already exists in this organization.')
        return name

    class Meta:
        model = Label
        fields = ['name', 'color']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 50}),
            'color': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color',
                'pattern': '#[0-9A-Fa-f]{6}',
            }),
        }

    def save(self, commit=True):
        label = super().save(commit=False)
        if self.organization and not label.organization_id:
            label.organization = self.organization
        if commit:
            label.save()
        return label


class ProjectForm(forms.ModelForm):
    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization is not None:
            self.organization = organization
        elif self.instance and getattr(self.instance, 'organization_id', None):
            self.organization = self.instance.organization
        else:
            self.organization = None

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        duplicates = Project.objects.filter(name__iexact=name)
        if self.organization:
            duplicates = duplicates.filter(organization=self.organization)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError('A project with this name already exists in this organization.')
        return name

    class Meta:
        model = Project
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 150}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def save(self, commit=True):
        project = super().save(commit=False)
        if self.organization and not project.organization_id:
            project.organization = self.organization
        if commit:
            project.save()
        return project


class TaskCommentForm(forms.ModelForm):
    parent = forms.ModelChoiceField(
        queryset=TaskComment.objects.all(),
        required=False,
        widget=forms.HiddenInput()
    )

    class Meta:
        model = TaskComment
        fields = ['content', 'parent']
        widgets = {
            'content': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Write a comment or update... Press Enter or Post.',
                'required': True
            }),
        }
