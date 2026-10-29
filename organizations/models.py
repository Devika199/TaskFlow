from django.conf import settings
from django.db import models
from django.utils.text import slugify


class Organization(models.Model):
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=150, unique=True, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    settings = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name) or 'org'
            slug = base_slug
            counter = 1
            while Organization.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def active_members(self):
        return self.memberships.filter(is_active=True).select_related('user')

    @property
    def owners(self):
        return self.memberships.filter(role=OrganizationMembership.ROLE_OWNER, is_active=True).select_related('user')

    @property
    def active_owner_count(self):
        return self.memberships.filter(role=OrganizationMembership.ROLE_OWNER, is_active=True).count()

    @property
    def has_active_owner(self):
        return self.active_owner_count > 0


class OrganizationMembership(models.Model):
    ROLE_OWNER = 'OWNER'
    ROLE_ADMIN = 'ADMIN'
    ROLE_MEMBER = 'MEMBER'

    ROLE_CHOICES = [
        (ROLE_OWNER, 'Owner'),
        (ROLE_ADMIN, 'Administrator'),
        (ROLE_MEMBER, 'Member'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='organization_memberships',
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='memberships',
    )
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default=ROLE_MEMBER,
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['organization', 'role', 'user__username']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'organization'],
                name='unique_user_organization_membership',
            ),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.organization.name} ({self.get_role_display()})"

    @property
    def is_owner(self):
        return self.is_active and self.role == self.ROLE_OWNER

    @property
    def is_admin(self):
        return self.is_active and self.role in (self.ROLE_OWNER, self.ROLE_ADMIN)

    @property
    def can_manage_members(self):
        return self.is_admin

    @property
    def can_manage_organization(self):
        return self.is_owner

