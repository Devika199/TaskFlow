from django.db import migrations, models


def create_default_organization(apps, schema_editor):
    Organization = apps.get_model('organizations', 'Organization')
    OrganizationMembership = apps.get_model('organizations', 'OrganizationMembership')
    User = apps.get_model('accounts', 'User')
    Task = apps.get_model('tasks', 'Task')
    Project = apps.get_model('tasks', 'Project')
    Label = apps.get_model('tasks', 'Label')
    Notification = apps.get_model('notifications', 'Notification')

    # Get or create the default workspace
    org, _ = Organization.objects.get_or_create(
        slug='default-workspace',
        defaults={'name': 'TaskFlow Workspace', 'is_active': True},
    )

    # Backfill memberships for existing users
    owner_assigned = False
    admin_users = User.objects.filter(models.Q(role='ADMIN') | models.Q(is_superuser=True)).order_by('id')

    for user in User.objects.all().order_by('id'):
        if not OrganizationMembership.objects.filter(user=user, organization=org).exists():
            if (user.role == 'ADMIN' or user.is_superuser) and not owner_assigned:
                membership_role = 'OWNER'
                owner_assigned = True
            elif user.role == 'ADMIN' or user.is_superuser:
                membership_role = 'ADMIN'
            else:
                membership_role = 'MEMBER'

            OrganizationMembership.objects.create(
                user=user,
                organization=org,
                role=membership_role,
                is_active=user.is_active,
            )

    # Ensure at least one active owner exists if users exist
    if not owner_assigned and User.objects.exists():
        first_membership = OrganizationMembership.objects.filter(organization=org).order_by('id').first()
        if first_membership:
            first_membership.role = 'OWNER'
            first_membership.save(update_fields=['role'])

    # Backfill existing tasks, projects, labels, notifications to default organization
    Task.objects.filter(organization__isnull=True).update(organization=org)
    Project.objects.filter(organization__isnull=True).update(organization=org)
    Label.objects.filter(organization__isnull=True).update(organization=org)
    Notification.objects.filter(organization__isnull=True).update(organization=org)


def reverse_default_organization(apps, schema_editor):
    Organization = apps.get_model('organizations', 'Organization')
    Organization.objects.filter(slug='default-workspace').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0001_initial'),
        ('tasks', '0003_label_organization_project_organization_and_more'),
        ('notifications', '0002_notification_organization'),
    ]

    operations = [
        migrations.RunPython(create_default_organization, reverse_default_organization),
    ]

