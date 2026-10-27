from django import forms
from django.contrib.auth import get_user_model
from .models import Task, TaskComment

User = get_user_model()


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ['title', 'description', 'status', 'priority', 'due_date', 'assigned_to']
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assigned_to'].queryset = User.objects.filter(is_active=True).order_by('first_name', 'username')
        self.fields['assigned_to'].empty_label = "Unassigned"


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
