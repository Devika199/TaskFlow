from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from notifications.models import Notification
from tasks.models import Task, TaskActivityLog, TaskComment

User = get_user_model()


class Command(BaseCommand):
    help = 'Seeds realistic demo data for the TaskFlow application'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Seeding TaskFlow demo data..."))

        # 1. Create Demo Users
        users_data = [
            {
                'username': 'alex.admin',
                'email': 'alex@taskflow.dev',
                'first_name': 'Alex',
                'last_name': 'Rivers',
                'role': User.ROLE_ADMIN,
                'department': 'Product & Engineering',
                'job_title': 'Head of Engineering',
                'avatar_color': '#4f46e5',
                'bio': 'Engineering leader driving SaaS architecture and team velocity.',
                'password': 'password123',
                'is_staff': True,
                'is_superuser': True,
            },
            {
                'username': 'sarah.tech',
                'email': 'sarah.chen@taskflow.dev',
                'first_name': 'Sarah',
                'last_name': 'Chen',
                'role': User.ROLE_MEMBER,
                'department': 'Backend Platform',
                'job_title': 'Senior Backend Engineer',
                'avatar_color': '#06b6d4',
                'bio': 'Specializing in Python, distributed systems, and API design.',
                'password': 'password123',
            },
            {
                'username': 'marcus.ui',
                'email': 'marcus.vance@taskflow.dev',
                'first_name': 'Marcus',
                'last_name': 'Vance',
                'role': User.ROLE_MEMBER,
                'department': 'Product Experience',
                'job_title': 'Lead Frontend Architect',
                'avatar_color': '#10b981',
                'bio': 'Passionate about modern component design, animations, and accessibility.',
                'password': 'password123',
            },
            {
                'username': 'elena.qa',
                'email': 'elena.rostova@taskflow.dev',
                'first_name': 'Elena',
                'last_name': 'Rostova',
                'role': User.ROLE_MEMBER,
                'department': 'Quality Assurance',
                'job_title': 'Senior QA Automation Engineer',
                'avatar_color': '#f59e0b',
                'bio': 'Ensuring zero-regression deployment pipelines and robust E2E test suites.',
                'password': 'password123',
            },
            {
                'username': 'david.product',
                'email': 'david.kim@taskflow.dev',
                'first_name': 'David',
                'last_name': 'Kim',
                'role': User.ROLE_ADMIN,
                'department': 'Product Management',
                'job_title': 'Principal Product Manager',
                'avatar_color': '#ec4899',
                'bio': 'Aligning business strategy, customer feedback, and agile sprints.',
                'password': 'password123',
            },
        ]

        users = {}
        for u in users_data:
            user, created = User.objects.get_or_create(
                username=u['username'],
                defaults={
                    'email': u['email'],
                    'first_name': u['first_name'],
                    'last_name': u['last_name'],
                    'role': u['role'],
                    'department': u['department'],
                    'job_title': u['job_title'],
                    'avatar_color': u['avatar_color'],
                    'bio': u['bio'],
                    'is_staff': u.get('is_staff', False),
                    'is_superuser': u.get('is_superuser', False),
                }
            )
            user.set_password(u['password'])
            user.save()
            users[u['username']] = user
            if created:
                self.stdout.write(f"Created user: {user.username}")

        admin_user = users['alex.admin']
        sarah = users['sarah.tech']
        marcus = users['marcus.ui']
        elena = users['elena.qa']
        david = users['david.product']

        # Clear existing demo tasks to avoid duplication when re-seeding
        Task.objects.all().delete()
        Notification.objects.all().delete()

        today = timezone.now().date()

        # 2. Tasks definition with realistic contexts
        tasks_data = [
            # High Priority / In Progress
            {
                'title': 'Implement OAuth 2.0 and Single Sign-On (SSO)',
                'description': 'Configure enterprise SSO integration for Google Workspace and GitHub OAuth providers. Ensure JWT refresh rotation and CSRF protection.',
                'status': Task.STATUS_IN_PROGRESS,
                'priority': Task.PRIORITY_HIGH,
                'due_date': today + timedelta(days=2),
                'created_by': david,
                'assigned_to': sarah,
            },
            {
                'title': 'Refactor Kanban Board with Drag-and-Drop SortableJS',
                'description': 'Replace legacy table with smooth HTML5 drag-and-drop Kanban columns. Include optimistic UI updates, roll-back on error, and column card counts.',
                'status': Task.STATUS_IN_PROGRESS,
                'priority': Task.PRIORITY_HIGH,
                'due_date': today + timedelta(days=1),
                'created_by': admin_user,
                'assigned_to': marcus,
            },
            # Overdue Tasks
            {
                'title': 'Security Audit: Patch Dependencies and Verify CSP Headers',
                'description': 'Run pip-audit and verify Content-Security-Policy rules. Ensure strict XSS protection and restrict external script injections.',
                'status': Task.STATUS_TODO,
                'priority': Task.PRIORITY_HIGH,
                'due_date': today - timedelta(days=2),
                'created_by': admin_user,
                'assigned_to': sarah,
            },
            {
                'title': 'Optimize Database Queries with select_related / prefetch_related',
                'description': 'N+1 query bottlenecks detected in the task list view when loading comments count and assignee records. Implement query profiling.',
                'status': Task.STATUS_IN_PROGRESS,
                'priority': Task.PRIORITY_MEDIUM,
                'due_date': today - timedelta(days=1),
                'created_by': sarah,
                'assigned_to': sarah,
            },
            # To Do Tasks
            {
                'title': 'Design Real-Time Notification Bell Drawer',
                'description': 'Create an interactive dropdown menu with live unread indicators, "Mark all as read" button, and auto-refresh polling.',
                'status': Task.STATUS_TODO,
                'priority': Task.PRIORITY_MEDIUM,
                'due_date': today + timedelta(days=4),
                'created_by': david,
                'assigned_to': marcus,
            },
            {
                'title': 'Automate E2E Regression Test Suite in Playwright',
                'description': 'Write comprehensive test scripts covering user registration, task creation, Kanban card moves, and comments threading.',
                'status': Task.STATUS_TODO,
                'priority': Task.PRIORITY_MEDIUM,
                'due_date': today + timedelta(days=5),
                'created_by': admin_user,
                'assigned_to': elena,
            },
            {
                'title': 'Export Workload Reports to CSV and PDF',
                'description': 'Enable enterprise team leads to export monthly sprint velocity and workload metrics in both CSV and formatted PDF formats.',
                'status': Task.STATUS_TODO,
                'priority': Task.PRIORITY_LOW,
                'due_date': today + timedelta(days=8),
                'created_by': david,
                'assigned_to': None, # Unassigned task for testing
            },
            # Completed Tasks
            {
                'title': 'Design SaaS System Architecture & ER Diagrams',
                'description': 'Document complete multi-tier architecture, relational schema in 3NF, API endpoint specifications, and security threat model.',
                'status': Task.STATUS_COMPLETED,
                'priority': Task.PRIORITY_HIGH,
                'due_date': today - timedelta(days=3),
                'created_by': admin_user,
                'assigned_to': admin_user,
            },
            {
                'title': 'Setup Bootstrap 5 SaaS Theme & Responsive Layout',
                'description': 'Establish consistent typography, modern sidebar navigation, dark/light accents, badges, and card elevation styling.',
                'status': Task.STATUS_COMPLETED,
                'priority': Task.PRIORITY_MEDIUM,
                'due_date': today - timedelta(days=2),
                'created_by': admin_user,
                'assigned_to': marcus,
            },
            {
                'title': 'Implement Role-Based Access Control Middleware',
                'description': 'Restrict access between Admin and Member roles. Ensure non-admins cannot mutate other users or access management dashboards.',
                'status': Task.STATUS_COMPLETED,
                'priority': Task.PRIORITY_HIGH,
                'due_date': today - timedelta(days=1),
                'created_by': david,
                'assigned_to': sarah,
            },
            {
                'title': 'Cross-Browser Testing on Mobile & Tablet Viewports',
                'description': 'Validate responsive breakpoints on Chrome, Safari iOS, and Firefox Android. Verify sidebar collapse drawer and touch targets.',
                'status': Task.STATUS_COMPLETED,
                'priority': Task.PRIORITY_LOW,
                'due_date': today - timedelta(days=1),
                'created_by': david,
                'assigned_to': elena,
            },
        ]

        created_tasks = []
        for td in tasks_data:
            task = Task.objects.create(
                title=td['title'],
                description=td['description'],
                status=td['status'],
                priority=td['priority'],
                due_date=td['due_date'],
                created_by=td['created_by'],
                assigned_to=td['assigned_to']
            )
            created_tasks.append(task)

            # Activity log
            TaskActivityLog.objects.create(
                task=task,
                actor=td['created_by'],
                action='CREATED',
                details=f"Task created by {td['created_by'].display_name}."
            )

            if td['status'] == Task.STATUS_COMPLETED:
                TaskActivityLog.objects.create(
                    task=task,
                    actor=td['assigned_to'] or td['created_by'],
                    action='STATUS_CHANGE',
                    details="Status updated to Completed."
                )

        # 3. Add Comments & Threaded Replies
        task_sso = created_tasks[0] # OAuth task
        c1 = TaskComment.objects.create(
            task=task_sso,
            author=sarah,
            content="I have set up the Google OAuth credentials in the staging console. Awaiting approval on client IDs."
        )
        TaskComment.objects.create(
            task=task_sso,
            author=admin_user,
            parent=c1,
            content="Client IDs approved! Staging redirect URI is configured to https://staging.taskflow.dev/oauth/callback."
        )
        TaskComment.objects.create(
            task=task_sso,
            author=sarah,
            parent=c1,
            content="Perfect, starting the token refresh middleware integration now."
        )

        task_kanban = created_tasks[1] # Kanban task
        c2 = TaskComment.objects.create(
            task=task_kanban,
            author=marcus,
            content="SortableJS is integrated with smooth drag transitions. Added ghost-card styling and automatic status synchronization via REST PATCH."
        )
        TaskComment.objects.create(
            task=task_kanban,
            author=david,
            parent=c2,
            content="Looks fantastic Marcus! Can we ensure column counters update instantaneously on card drop?"
        )

        # 4. Add Notifications
        Notification.objects.create(
            recipient=sarah,
            actor=david,
            task=task_sso,
            verb="assigned you to task 'Implement OAuth 2.0 and Single Sign-On (SSO)'",
            notification_type=Notification.TYPE_ASSIGNMENT,
            is_read=False
        )
        Notification.objects.create(
            recipient=sarah,
            actor=admin_user,
            task=task_sso,
            verb="replied to your comment on 'Implement OAuth 2.0 and Single Sign-On (SSO)'",
            notification_type=Notification.TYPE_COMMENT,
            is_read=False
        )
        Notification.objects.create(
            recipient=marcus,
            actor=admin_user,
            task=task_kanban,
            verb="assigned you to task 'Refactor Kanban Board with Drag-and-Drop SortableJS'",
            notification_type=Notification.TYPE_ASSIGNMENT,
            is_read=True
        )
        Notification.objects.create(
            recipient=admin_user,
            actor=marcus,
            task=task_kanban,
            verb="commented on 'Refactor Kanban Board with Drag-and-Drop SortableJS'",
            notification_type=Notification.TYPE_COMMENT,
            is_read=False
        )

        self.stdout.write(self.style.SUCCESS("Demo data seeded successfully!"))
        self.stdout.write(self.style.SUCCESS("Demo credentials:"))
        self.stdout.write("  Admin: alex.admin / password123")
        self.stdout.write("  Member: sarah.tech / password123")
        self.stdout.write("  Member: marcus.ui / password123")
