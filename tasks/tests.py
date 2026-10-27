from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from tasks.models import Task, TaskActivityLog, TaskComment

User = get_user_model()


class TasksTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin_task',
            email='admin@tasks.com',
            password='password123',
            role=User.ROLE_ADMIN
        )
        self.member = User.objects.create_user(
            username='member_task',
            email='member@tasks.com',
            password='password123',
            role=User.ROLE_MEMBER
        )
        self.other_member = User.objects.create_user(
            username='other_member',
            email='other@tasks.com',
            password='password123',
            role=User.ROLE_MEMBER
        )

        today = timezone.now().date()
        self.task_overdue = Task.objects.create(
            title='Overdue Task',
            description='Should be marked overdue',
            status=Task.STATUS_TODO,
            priority=Task.PRIORITY_HIGH,
            due_date=today - timedelta(days=2),
            created_by=self.admin,
            assigned_to=self.member
        )
        self.task_completed = Task.objects.create(
            title='Done Task',
            description='Already completed',
            status=Task.STATUS_COMPLETED,
            priority=Task.PRIORITY_LOW,
            due_date=today - timedelta(days=5),
            created_by=self.admin,
            assigned_to=self.member
        )

    def test_overdue_property(self):
        self.assertTrue(self.task_overdue.is_overdue)
        # Even though due date is past, completed tasks should not be overdue
        self.assertFalse(self.task_completed.is_overdue)

    def test_completed_at_timestamp_auto_set(self):
        self.assertIsNotNone(self.task_completed.completed_at)

        # Move overdue task to completed
        self.task_overdue.status = Task.STATUS_COMPLETED
        self.task_overdue.save()
        self.assertIsNotNone(self.task_overdue.completed_at)

    def test_task_permissions(self):
        # Admin can edit and delete anything
        self.assertTrue(self.task_overdue.can_edit(self.admin))
        self.assertTrue(self.task_overdue.can_delete(self.admin))

        # Assignee can edit, but cannot delete if not creator
        self.assertTrue(self.task_overdue.can_edit(self.member))
        self.assertFalse(self.task_overdue.can_delete(self.member))

        # Other member cannot edit or delete
        self.assertFalse(self.task_overdue.can_edit(self.other_member))
        self.assertFalse(self.task_overdue.can_delete(self.other_member))

    def test_create_task_view(self):
        self.client.login(username='admin_task', password='password123')
        response = self.client.post(reverse('task_create'), {
            'title': 'New Feature Task',
            'description': 'Details here',
            'status': Task.STATUS_TODO,
            'priority': Task.PRIORITY_MEDIUM,
            'due_date': timezone.now().date() + timedelta(days=3),
            'assigned_to': self.member.id
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Task.objects.filter(title='New Feature Task').exists())

    def test_comments_and_replies(self):
        self.client.login(username='member_task', password='password123')
        # Add root comment
        response = self.client.post(reverse('add_comment', args=[self.task_overdue.id]), {
            'content': 'Root comment on overdue task'
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        root_comment = TaskComment.objects.get(content='Root comment on overdue task')
        self.assertEqual(root_comment.author, self.member)

        # Add threaded reply
        response = self.client.post(reverse('add_comment', args=[self.task_overdue.id]), {
            'content': 'Threaded reply from admin',
            'parent': root_comment.id
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        reply = TaskComment.objects.get(content='Threaded reply from admin')
        self.assertEqual(reply.parent, root_comment)
