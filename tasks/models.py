from django.conf import settings
from django.db import models
from django.utils import timezone


class Task(models.Model):
    STATUS_TODO = 'TODO'
    STATUS_IN_PROGRESS = 'IN_PROGRESS'
    STATUS_COMPLETED = 'COMPLETED'

    STATUS_CHOICES = [
        (STATUS_TODO, 'To Do'),
        (STATUS_IN_PROGRESS, 'In Progress'),
        (STATUS_COMPLETED, 'Completed'),
    ]

    PRIORITY_LOW = 'LOW'
    PRIORITY_MEDIUM = 'MEDIUM'
    PRIORITY_HIGH = 'HIGH'

    PRIORITY_CHOICES = [
        (PRIORITY_LOW, 'Low'),
        (PRIORITY_MEDIUM, 'Medium'),
        (PRIORITY_HIGH, 'High'),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_TODO,
        db_index=True
    )
    priority = models.CharField(
        max_length=20,
        choices=PRIORITY_CHOICES,
        default=PRIORITY_MEDIUM,
        db_index=True
    )
    due_date = models.DateField(null=True, blank=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_tasks'
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_tasks',
        db_index=True
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'assigned_to']),
            models.Index(fields=['due_date', 'status']),
        ]

    def __str__(self):
        return self.title

    @property
    def is_overdue(self):
        if self.due_date and self.status != self.STATUS_COMPLETED:
            return self.due_date < timezone.now().date()
        return False

    @property
    def due_status(self):
        if not self.due_date:
            return 'none'
        today = timezone.now().date()
        if self.status == self.STATUS_COMPLETED:
            return 'completed'
        if self.due_date < today:
            return 'overdue'
        if self.due_date == today:
            return 'today'
        diff = (self.due_date - today).days
        if diff <= 3:
            return 'soon'
        return 'upcoming'

    def save(self, *args, **kwargs):
        if self.status == self.STATUS_COMPLETED:
            if not self.completed_at:
                self.completed_at = timezone.now()
        else:
            self.completed_at = None
        super().save(*args, **kwargs)

    def can_view(self, user):
        if not user or not user.is_authenticated:
            return False
        if user.is_admin_role:
            return True
        return self.assigned_to_id == user.id

    def can_edit(self, user):
        if not user or not user.is_authenticated:
            return False
        return bool(user.is_admin_role)

    def can_delete(self, user):
        if not user or not user.is_authenticated:
            return False
        return bool(user.is_admin_role)

    def can_update_status(self, user):
        if not user or not user.is_authenticated:
            return False
        if user.is_admin_role:
            return True
        return self.assigned_to_id == user.id

    def can_comment(self, user):
        return self.can_view(user)


class TaskComment(models.Model):
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='comments'
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='task_comments'
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='replies'
    )
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Comment by {self.author.username} on {self.task.title}"

    def can_delete(self, user):
        if not user or not user.is_authenticated:
            return False
        if user.is_admin_role:
            return True
        return self.author_id == user.id


class TaskActivityLog(models.Model):
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='activity_logs'
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='task_activities'
    )
    action = models.CharField(max_length=50)
    details = models.TextField(blank=True, default='')
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.action} on {self.task.title} at {self.timestamp}"
