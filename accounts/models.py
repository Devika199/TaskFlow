from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    ROLE_ADMIN = 'ADMIN'
    ROLE_MEMBER = 'MEMBER'
    ROLE_CHOICES = [
        (ROLE_ADMIN, 'Administrator'),
        (ROLE_MEMBER, 'Team Member'),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_MEMBER)
    department = models.CharField(max_length=100, blank=True, default='')
    job_title = models.CharField(max_length=100, blank=True, default='')
    avatar_color = models.CharField(max_length=10, default='#4f46e5')
    bio = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['username']

    @property
    def is_admin_role(self):
        return self.role == self.ROLE_ADMIN or self.is_superuser or self.is_staff

    @property
    def display_name(self):
        if self.first_name or self.last_name:
            return f"{self.first_name} {self.last_name}".strip()
        return self.username

    @property
    def initials(self):
        first = self.first_name[0].upper() if self.first_name else ''
        last = self.last_name[0].upper() if self.last_name else ''
        if first and last:
            return f"{first}{last}"
        return (self.username[:2]).upper()

    def __str__(self):
        return f"{self.display_name} ({self.get_role_display()})"
