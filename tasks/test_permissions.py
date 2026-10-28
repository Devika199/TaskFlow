from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from notifications.models import Notification
from tasks.models import Task, TaskComment

User = get_user_model()


PROTECTED_NAMED_URLS = [
    ('dashboard', {}),
    ('task_list', {}),
    ('kanban', {}),
    ('task_create', {}),
    ('profile', {}),
    ('user_management', {}),
    ('analytics_dashboard', {}),
    ('notification_list', {}),
]


class ViewPermissionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='perm_admin',
            email='perm_admin@test.com',
            password='password123',
            role=User.ROLE_ADMIN,
        )
        self.member = User.objects.create_user(
            username='perm_member',
            email='perm_member@test.com',
            password='password123',
            role=User.ROLE_MEMBER,
        )
        self.other_member = User.objects.create_user(
            username='perm_other',
            email='perm_other@test.com',
            password='password123',
            role=User.ROLE_MEMBER,
        )
        self.own_task = Task.objects.create(
            title='Assigned to member',
            description='Own task',
            status=Task.STATUS_TODO,
            priority=Task.PRIORITY_MEDIUM,
            created_by=self.admin,
            assigned_to=self.member,
        )
        self.other_task = Task.objects.create(
            title='Assigned to other',
            description='Not this member',
            status=Task.STATUS_TODO,
            priority=Task.PRIORITY_HIGH,
            created_by=self.admin,
            assigned_to=self.other_member,
        )
        self.admin_comment = TaskComment.objects.create(
            task=self.own_task,
            author=self.admin,
            content='Admin comment',
        )
        self.member_comment = TaskComment.objects.create(
            task=self.own_task,
            author=self.member,
            content='Member comment',
        )
        self.other_notification = Notification.objects.create(
            recipient=self.other_member,
            actor=self.admin,
            verb='other user notification',
            task=self.other_task,
            notification_type=Notification.TYPE_ASSIGNMENT,
        )

    def _assert_unauthenticated(self, response):
        self.assertIn(response.status_code, (302, 401, 403))
        if response.status_code == 302:
            self.assertIn(reverse('login'), response.url)

    def test_anonymous_users_cannot_access_protected_routes(self):
        for name, kwargs in PROTECTED_NAMED_URLS:
            with self.subTest(url=name):
                response = self.client.get(reverse(name, kwargs=kwargs))
                self._assert_unauthenticated(response)

        detail_urls = [
            reverse('task_detail', args=[self.own_task.pk]),
            reverse('task_edit', args=[self.own_task.pk]),
            reverse('task_delete', args=[self.own_task.pk]),
            reverse('update_task_status', args=[self.own_task.pk]),
            reverse('toggle_user_active', args=[self.member.pk]),
            reverse('mark_notification_read', args=[self.other_notification.pk]),
            reverse('delete_comment', args=[self.member_comment.pk]),
        ]
        for url in detail_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self._assert_unauthenticated(response)

    def test_member_cannot_create_edit_delete_or_reassign_tasks(self):
        self.client.login(username='perm_member', password='password123')

        create_get = self.client.get(reverse('task_create'))
        self.assertEqual(create_get.status_code, 403)

        create_post = self.client.post(reverse('task_create'), {
            'title': 'Member created task',
            'description': 'Should be denied',
            'status': Task.STATUS_TODO,
            'priority': Task.PRIORITY_LOW,
            'assigned_to': self.member.id,
        })
        self.assertEqual(create_post.status_code, 403)
        self.assertFalse(Task.objects.filter(title='Member created task').exists())

        edit_get = self.client.get(reverse('task_edit', args=[self.own_task.pk]))
        self.assertEqual(edit_get.status_code, 403)

        original_title = self.own_task.title
        original_assignee = self.own_task.assigned_to_id
        edit_post = self.client.post(reverse('task_edit', args=[self.own_task.pk]), {
            'title': 'Hijacked title',
            'description': 'Hijacked',
            'status': Task.STATUS_IN_PROGRESS,
            'priority': Task.PRIORITY_HIGH,
            'assigned_to': self.other_member.id,
        })
        self.assertEqual(edit_post.status_code, 403)
        self.own_task.refresh_from_db()
        self.assertEqual(self.own_task.title, original_title)
        self.assertEqual(self.own_task.assigned_to_id, original_assignee)

        delete_get = self.client.get(reverse('task_delete', args=[self.own_task.pk]))
        self.assertEqual(delete_get.status_code, 403)
        delete_post = self.client.post(reverse('task_delete', args=[self.own_task.pk]))
        self.assertEqual(delete_post.status_code, 403)
        self.assertTrue(Task.objects.filter(pk=self.own_task.pk).exists())

    def test_member_cannot_view_or_change_status_of_unassigned_task(self):
        self.client.login(username='perm_member', password='password123')

        detail = self.client.get(reverse('task_detail', args=[self.other_task.pk]))
        self.assertEqual(detail.status_code, 404)
        self.assertEqual(
            detail.status_code,
            self.client.get(reverse('task_detail', args=[999999])).status_code,
        )

        status_post = self.client.post(
            reverse('update_task_status', args=[self.other_task.pk]),
            {'status': Task.STATUS_IN_PROGRESS},
        )
        self.assertEqual(status_post.status_code, 404)
        self.other_task.refresh_from_db()
        self.assertEqual(self.other_task.status, Task.STATUS_TODO)

        hidden_comment = self.client.post(
            reverse('add_comment', args=[self.other_task.pk]),
            {'content': 'Hidden comment'},
        )
        missing_comment = self.client.post(
            reverse('add_comment', args=[999999]),
            {'content': 'Missing comment'},
        )
        self.assertEqual(hidden_comment.status_code, 404)
        self.assertEqual(hidden_comment.status_code, missing_comment.status_code)
        self.assertEqual(
            self.client.get(reverse('task_edit', args=[self.other_task.pk])).status_code,
            404,
        )

    def test_member_can_change_only_status_on_own_task(self):
        self.client.login(username='perm_member', password='password123')

        detail = self.client.get(reverse('task_detail', args=[self.own_task.pk]))
        self.assertEqual(detail.status_code, 200)

        status_post = self.client.post(
            reverse('update_task_status', args=[self.own_task.pk]),
            {'status': Task.STATUS_IN_PROGRESS},
        )
        self.assertIn(status_post.status_code, (200, 302))
        self.own_task.refresh_from_db()
        self.assertEqual(self.own_task.status, Task.STATUS_IN_PROGRESS)
        self.assertEqual(self.own_task.title, 'Assigned to member')
        self.assertEqual(self.own_task.assigned_to_id, self.member.id)
        self.assertEqual(self.own_task.priority, Task.PRIORITY_MEDIUM)

    def test_user_cannot_mark_another_users_notification_as_read(self):
        self.client.login(username='perm_member', password='password123')
        response = self.client.post(
            reverse('mark_notification_read', args=[self.other_notification.pk]),
        )
        self.assertIn(response.status_code, (403, 404))
        self.other_notification.refresh_from_db()
        self.assertFalse(self.other_notification.is_read)

    def test_only_comment_author_or_admin_can_delete_comment(self):
        self.client.login(username='perm_member', password='password123')
        denied = self.client.post(
            reverse('delete_comment', args=[self.admin_comment.pk]),
        )
        self.assertEqual(denied.status_code, 403)
        self.assertTrue(TaskComment.objects.filter(pk=self.admin_comment.pk).exists())

        allowed_own = self.client.post(
            reverse('delete_comment', args=[self.member_comment.pk]),
        )
        self.assertIn(allowed_own.status_code, (200, 302))
        self.assertFalse(TaskComment.objects.filter(pk=self.member_comment.pk).exists())

        other_comment = TaskComment.objects.create(
            task=self.own_task,
            author=self.other_member,
            content='Other member comment',
        )
        denied_other = self.client.post(
            reverse('delete_comment', args=[other_comment.pk]),
        )
        self.assertEqual(denied_other.status_code, 403)
        self.assertTrue(TaskComment.objects.filter(pk=other_comment.pk).exists())

        self.client.logout()
        self.client.login(username='perm_admin', password='password123')
        admin_delete = self.client.post(
            reverse('delete_comment', args=[other_comment.pk]),
        )
        self.assertIn(admin_delete.status_code, (200, 302))
        self.assertFalse(TaskComment.objects.filter(pk=other_comment.pk).exists())

    def test_member_cannot_access_team_management_or_analytics(self):
        self.client.login(username='perm_member', password='password123')
        self.assertEqual(self.client.get(reverse('user_management')).status_code, 403)
        self.assertEqual(
            self.client.post(reverse('toggle_user_active', args=[self.other_member.pk])).status_code,
            403,
        )
        self.assertEqual(self.client.get(reverse('analytics_dashboard')).status_code, 403)
        self.other_member.refresh_from_db()
        self.assertTrue(self.other_member.is_active)
