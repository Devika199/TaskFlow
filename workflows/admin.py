from django.contrib import admin
from .models import WorkflowExecution, WorkflowRule


@admin.register(WorkflowRule)
class WorkflowRuleAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization', 'trigger_type', 'is_enabled', 'created_at')
    list_filter = ('organization', 'trigger_type', 'is_enabled')
    search_fields = ('name', 'description')


@admin.register(WorkflowExecution)
class WorkflowExecutionAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'rule', 'triggering_event', 'status', 'created_at')
    list_filter = ('organization', 'status', 'triggering_event')
    search_fields = ('rule__name', 'idempotency_key', 'error_summary')
    readonly_fields = ('created_at', 'completed_at', 'idempotency_key')
