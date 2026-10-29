from django.conf import settings
from django.db import models


class Notification(models.Model):
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notifications',
    )
    TYPE_ASSIGNMENT = 'ASSIGNMENT'
    TYPE_STATUS_CHANGE = 'STATUS_CHANGE'
    TYPE_COMMENT = 'COMMENT'
    TYPE_SYSTEM = 'SYSTEM'

    TYPE_CHOICES = [
        (TYPE_ASSIGNMENT, 'Task Assignment'),
        (TYPE_STATUS_CHANGE, 'Status Changed'),
        (TYPE_COMMENT, 'New Comment'),
        (TYPE_SYSTEM, 'System Alert'),
    ]

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
        db_index=True
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='triggered_notifications'
    )
    task = models.ForeignKey(
        'tasks.Task',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notifications'
    )
    verb = models.CharField(max_length=255)
    notification_type = models.CharField(
        max_length=50,
        choices=TYPE_CHOICES,
        default=TYPE_SYSTEM
    )
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'is_read']),
            models.Index(fields=['recipient', 'created_at']),
        ]

    def save(self, *args, **kwargs):
        if not self.organization_id:
            if self.task and self.task.organization_id:
                self.organization = self.task.organization
            elif self.recipient:
                mem = self.recipient.organization_memberships.filter(is_active=True).first()
                if mem:
                    self.organization = mem.organization
            if not self.organization_id:
                from organizations.services import ensure_default_organization
                default_org, _ = ensure_default_organization()
                self.organization = default_org
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Notification for {self.recipient.username}: {self.verb}"
