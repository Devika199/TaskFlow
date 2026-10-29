from django.contrib import admin
from .models import Label, Project, Task, TaskActivityLog, TaskChecklistItem, TaskComment, TaskReminderLog


@admin.register(TaskReminderLog)
class TaskReminderLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'task', 'recipient', 'reminder_type', 'target_due_date', 'status', 'created_at')
    list_filter = ('organization', 'reminder_type', 'status', 'created_at')
    search_fields = ('task__title', 'recipient__username', 'idempotency_key')
    readonly_fields = ('created_at', 'sent_at', 'idempotency_key')


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'organization', 'status', 'priority', 'due_date', 'assigned_to', 'created_at')
    list_filter = ('organization', 'status', 'priority')
    search_fields = ('title', 'description')
