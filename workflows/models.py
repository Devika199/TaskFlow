from django.conf import settings
from django.db import models
from django.utils import timezone


class WorkflowRule(models.Model):
    TRIGGER_TASK_CREATED = 'TASK_CREATED'
    TRIGGER_TASK_ASSIGNED = 'TASK_ASSIGNED'
    TRIGGER_TASK_STATUS_CHANGED = 'TASK_STATUS_CHANGED'
    TRIGGER_TASK_COMPLETED = 'TASK_COMPLETED'

    TRIGGER_CHOICES = [
        (TRIGGER_TASK_CREATED, 'Task Created'),
        (TRIGGER_TASK_ASSIGNED, 'Task Assigned or Reassigned'),
        (TRIGGER_TASK_STATUS_CHANGED, 'Task Status Changed'),
        (TRIGGER_TASK_COMPLETED, 'Task Completed'),
    ]

    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='workflow_rules',
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_enabled = models.BooleanField(default=True, db_index=True)
    trigger_type = models.CharField(
        max_length=50,
        choices=TRIGGER_CHOICES,
        db_index=True,
    )
    conditions = models.JSONField(default=dict, blank=True)
    actions = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_workflow_rules',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'trigger_type', 'is_enabled']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'name'],
                name='unique_rule_name_per_organization',
            ),
        ]

    def __str__(self):
        return f"{self.name} [{self.trigger_type}] ({self.organization.name})"

    @property
    def executions_count(self):
        return self.executions.count()

    @property
    def last_execution(self):
        return self.executions.order_by('-created_at').first()


class WorkflowExecution(models.Model):
    STATUS_PENDING = 'PENDING'
    STATUS_RUNNING = 'RUNNING'
    STATUS_SUCCESS = 'SUCCESS'
    STATUS_FAILED = 'FAILED'
    STATUS_SKIPPED = 'SKIPPED'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_RUNNING, 'Running'),
        (STATUS_SUCCESS, 'Success'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_SKIPPED, 'Skipped'),
    ]

    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='workflow_executions',
    )
    rule = models.ForeignKey(
        WorkflowRule,
        on_delete=models.CASCADE,
        related_name='executions',
    )
    triggering_event = models.CharField(max_length=50)
    task = models.ForeignKey(
        'tasks.Task',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='workflow_executions',
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    idempotency_key = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
    )
    execution_log = models.JSONField(default=dict, blank=True)
    error_summary = models.TextField(blank=True)
    retry_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'status', 'created_at']),
            models.Index(fields=['rule', '-created_at']),
        ]

    def __str__(self):
        return f"Execution {self.id} for {self.rule.name} [{self.status}]"

    def mark_completed(self, status=STATUS_SUCCESS, log=None, error_summary=''):
        self.status = status
        self.completed_at = timezone.now()
        if log is not None:
            self.execution_log = log
        if error_summary:
            self.error_summary = error_summary[:1000]
        self.save(update_fields=['status', 'completed_at', 'execution_log', 'error_summary'])
