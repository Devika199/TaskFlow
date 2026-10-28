from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from .models import Label, Project, Task, TaskChecklistItem, TaskComment

User = get_user_model()


class TaskForm(forms.ModelForm):
    labels = forms.ModelMultipleChoiceField(
        queryset=Label.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={
            'class': 'form-select',
            'aria-describedby': 'labels-help',
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
            'project': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assigned_to'].queryset = User.objects.filter(is_active=True).order_by('first_name', 'username')
        self.fields['assigned_to'].empty_label = "Unassigned"
        projects = Project.objects.filter(archived=False)
        if self.instance and self.instance.pk and self.instance.project_id:
            projects = Project.objects.filter(Q(archived=False) | Q(pk=self.instance.project_id))
        self.fields['project'].queryset = projects.order_by('name')
        self.fields['project'].required = False


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
    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        duplicates = Label.objects.filter(name__iexact=name)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError('A label with this name already exists.')
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


class ProjectForm(forms.ModelForm):
    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        duplicates = Project.objects.filter(name__iexact=name)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError('A project with this name already exists.')
        return name

    class Meta:
        model = Project
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 150}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


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
