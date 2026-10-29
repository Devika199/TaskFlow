from django.conf import settings
from django.db import models
from django.core.validators import RegexValidator
from django.utils import timezone


class Project(models.Model):
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='projects',
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default='')
    archived = models.BooleanField(default=False, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_projects',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'name'], name='unique_project_name_per_org'),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.organization_id:
            from organizations.services import ensure_default_organization
            if self.created_by:
                mem = self.created_by.organization_memberships.filter(is_active=True).first()
                if mem:
                    self.organization = mem.organization
            if not self.organization_id:
                default_org, _ = ensure_default_organization()
                self.organization = default_org
        super().save(*args, **kwargs)


class Label(models.Model):
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='labels',
    )
    name = models.CharField(max_length=50)
    color = models.CharField(
        max_length=7,
        default='#4f46e5',
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Enter a valid hex colour such as #4f46e5.')],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'name'], name='unique_label_name_per_org'),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.organization_id:
            from organizations.services import ensure_default_organization
            default_org, _ = ensure_default_organization()
            self.organization = default_org
        super().save(*args, **kwargs)


def _get_user_org_cache(user):
    if not user or not user.is_authenticated:
        return set(), set(), False
    cached = getattr(user, '_taskflow_org_cache', None)
    if cached is not None:
        return cached
    memberships = list(user.organization_memberships.filter(is_active=True).values('organization_id', 'role'))
    has_any = len(memberships) > 0 or user.organization_memberships.exists()
    active_ids = {m['organization_id'] for m in memberships}
    admin_ids = {m['organization_id'] for m in memberships if m['role'] in ('OWNER', 'ADMIN')}
    cached = (active_ids, admin_ids, has_any)
    try:
        user._taskflow_org_cache = cached
    except Exception:
        pass
    return cached


class Task(models.Model):
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='tasks',
        db_index=True,
    )
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
    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tasks',
    )
    labels = models.ManyToManyField(Label, blank=True, related_name='tasks')

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
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['organization', 'assigned_to']),
            models.Index(fields=['organization', 'due_date']),
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

    @property
    def checklist_total(self):
        return len(self.checklist_items.all())

    @property
    def checklist_completed(self):
        return sum(item.is_completed for item in self.checklist_items.all())

    @property
    def checklist_progress(self):
        total = self.checklist_total
        return round(self.checklist_completed / total * 100) if total else 0

    def save(self, *args, **kwargs):
        if not self.organization_id:
            from organizations.services import ensure_default_organization
            if self.created_by:
                mem = self.created_by.organization_memberships.filter(is_active=True).first()
                if mem:
                    self.organization = mem.organization
            if not self.organization_id and self.assigned_to:
                mem = self.assigned_to.organization_memberships.filter(is_active=True).first()
                if mem:
                    self.organization = mem.organization
            if not self.organization_id and self.project and self.project.organization_id:
                self.organization = self.project.organization
            if not self.organization_id:
                default_org, _ = ensure_default_organization()
                self.organization = default_org

        if self.status == self.STATUS_COMPLETED:
            if not self.completed_at:
                self.completed_at = timezone.now()
        else:
            self.completed_at = None
        super().save(*args, **kwargs)

    def _user_has_active_org_access(self, user):
        if not user or not user.is_authenticated:
            return False
        if not self.organization_id:
            return True
        active_ids, _, has_any = _get_user_org_cache(user)
        if not has_any:
            return True
        return self.organization_id in active_ids

    def can_view(self, user):
        if not self._user_has_active_org_access(user):
            return False
        active_ids, admin_ids, has_any = _get_user_org_cache(user)
        if not has_any:
            return bool(user.is_admin_role or self.assigned_to_id == user.id)
        if self.organization_id in admin_ids:
            return True
        return self.assigned_to_id == user.id

    def can_edit(self, user):
        if not self._user_has_active_org_access(user):
            return False
        active_ids, admin_ids, has_any = _get_user_org_cache(user)
        if not has_any:
            return bool(user.is_admin_role)
        return self.organization_id in admin_ids

    def can_delete(self, user):
        return self.can_edit(user)

    def can_update_status(self, user):
        if not self._user_has_active_org_access(user):
            return False
        active_ids, admin_ids, has_any = _get_user_org_cache(user)
        if not has_any:
            return bool(user.is_admin_role or self.assigned_to_id == user.id)
        if self.organization_id in admin_ids:
            return True
        return self.assigned_to_id == user.id

    def can_comment(self, user):
        return self.can_view(user)


class TaskChecklistItem(models.Model):
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='checklist_items',
    )
    title = models.CharField(max_length=255)
    position = models.PositiveIntegerField(default=0)
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['position', 'id']
        indexes = [models.Index(fields=['task', 'position'])]

    def __str__(self):
        return self.title


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
        active_ids, admin_ids, has_any = _get_user_org_cache(user)
        if has_any and self.task.organization_id and self.task.organization_id not in active_ids:
            return False
        if has_any and self.task.organization_id in admin_ids:
            return True
        if not has_any and user.is_admin_role:
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


class TaskReminderLog(models.Model):
    REMINDER_DUE_SOON = 'DUE_SOON'
    REMINDER_OVERDUE = 'OVERDUE'

    REMINDER_TYPE_CHOICES = [
        (REMINDER_DUE_SOON, 'Due Soon'),
        (REMINDER_OVERDUE, 'Overdue'),
    ]

    STATUS_PENDING = 'PENDING'
    STATUS_SENT = 'SENT'
    STATUS_SKIPPED = 'SKIPPED'
    STATUS_FAILED = 'FAILED'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SENT, 'Sent'),
        (STATUS_SKIPPED, 'Skipped'),
        (STATUS_FAILED, 'Failed'),
    ]

    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='task_reminder_logs',
        db_index=True,
    )
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='reminder_logs',
        db_index=True,
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='task_reminder_logs',
    )
    reminder_type = models.CharField(
        max_length=20,
        choices=REMINDER_TYPE_CHOICES,
        db_index=True,
    )
    target_due_date = models.DateField(
        help_text="The task due date for which this reminder was issued",
        db_index=True,
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    idempotency_key = models.CharField(
        max_length=150,
        unique=True,
        db_index=True,
    )
    notification = models.ForeignKey(
        'notifications.Notification',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reminder_logs',
    )
    error_summary = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'status', 'created_at']),
            models.Index(fields=['task', 'reminder_type', 'target_due_date']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['task', 'reminder_type', 'target_due_date'],
                name='unique_task_reminder_per_period',
            ),
        ]

    def __str__(self):
        return f"{self.reminder_type} for Task #{self.task_id} ({self.target_due_date}) - {self.status}"

