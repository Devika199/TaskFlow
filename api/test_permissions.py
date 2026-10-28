from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from notifications.models import Notification
from tasks.models import Task, TaskComment

User = get_user_model()


class APIPermissionTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username='api_perm_admin',
            email='api_perm_admin@test.com',
            password='password123',
            role=User.ROLE_ADMIN,
        )
        self.member = User.objects.create_user(
            username='api_perm_member',
            email='api_perm_member@test.com',
            password='password123',
            role=User.ROLE_MEMBER,
        )
        self.other_member = User.objects.create_user(
            username='api_perm_other',
            email='api_perm_other@test.com',
            password='password123',
            role=User.ROLE_MEMBER,
        )
        self.own_task = Task.objects.create(
            title='API own task',
            description='Assigned to member',
            status=Task.STATUS_TODO,
            priority=Task.PRIORITY_MEDIUM,
            created_by=self.admin,
            assigned_to=self.member,
        )
        self.other_task = Task.objects.create(
            title='API other task',
            description='Assigned to other member',
            status=Task.STATUS_TODO,
            priority=Task.PRIORITY_HIGH,
            created_by=self.admin,
            assigned_to=self.other_member,
        )
        self.admin_comment = TaskComment.objects.create(
            task=self.own_task,
            author=self.admin,
            content='API admin comment',
        )
        self.member_comment = TaskComment.objects.create(
            task=self.own_task,
            author=self.member,
            content='API member comment',
        )
        self.other_notification = Notification.objects.create(
            recipient=self.other_member,
            actor=self.admin,
            verb='API other notification',
            task=self.other_task,
            notification_type=Notification.TYPE_ASSIGNMENT,
        )

    def _assert_auth_required(self, response):
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_anonymous_users_cannot_access_protected_api_routes(self):
        urls = [
            '/api/v1/tasks/',
            f'/api/v1/tasks/{self.own_task.pk}/',
            '/api/v1/comments/',
            '/api/v1/notifications/',
            '/api/v1/auth/me/',
            '/api/v1/analytics/overview/',
            '/api/v1/analytics/workload/',
            '/api/v1/users/',
        ]
        for url in urls:
            with self.subTest(url=url):
                self._assert_auth_required(self.client.get(url))

        self._assert_auth_required(self.client.post('/api/v1/tasks/', {'title': 'x'}))
        self._assert_auth_required(
            self.client.patch(f'/api/v1/tasks/{self.own_task.pk}/update-status/', {'status': 'IN_PROGRESS'})
        )
        self._assert_auth_required(
            self.client.post(f'/api/v1/notifications/{self.other_notification.pk}/mark-read/')
        )

    def test_member_cannot_create_edit_delete_or_reassign_tasks(self):
        self.client.force_authenticate(user=self.member)

        create = self.client.post('/api/v1/tasks/', {
            'title': 'Member API create',
            'description': 'Denied',
            'status': 'TODO',
            'priority': 'LOW',
            'assigned_to': self.member.id,
        })
        self.assertEqual(create.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Task.objects.filter(title='Member API create').exists())

        original_title = self.own_task.title
        original_assignee = self.own_task.assigned_to_id
        patch = self.client.patch(f'/api/v1/tasks/{self.own_task.pk}/', {
            'title': 'Hijacked API title',
            'assigned_to': self.other_member.id,
            'priority': 'HIGH',
        }, format='json')
        self.assertEqual(patch.status_code, status.HTTP_403_FORBIDDEN)
        self.own_task.refresh_from_db()
        self.assertEqual(self.own_task.title, original_title)
        self.assertEqual(self.own_task.assigned_to_id, original_assignee)
        self.assertEqual(self.own_task.priority, Task.PRIORITY_MEDIUM)

        put = self.client.put(f'/api/v1/tasks/{self.own_task.pk}/', {
            'title': 'Full replace',
            'description': 'Denied',
            'status': 'COMPLETED',
            'priority': 'HIGH',
            'assigned_to': self.other_member.id,
        }, format='json')
        self.assertEqual(put.status_code, status.HTTP_403_FORBIDDEN)

        delete = self.client.delete(f'/api/v1/tasks/{self.own_task.pk}/')
        self.assertEqual(delete.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Task.objects.filter(pk=self.own_task.pk).exists())

    def test_member_cannot_view_or_change_status_of_unassigned_task(self):
        self.client.force_authenticate(user=self.member)

        retrieve = self.client.get(f'/api/v1/tasks/{self.other_task.pk}/')
        self.assertEqual(retrieve.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            retrieve.status_code,
            self.client.get('/api/v1/tasks/999999/').status_code,
        )

        listed = self.client.get('/api/v1/tasks/')
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        titles = [item['title'] for item in listed.data['results']]
        self.assertIn('API own task', titles)
        self.assertNotIn('API other task', titles)

        status_change = self.client.patch(
            f'/api/v1/tasks/{self.other_task.pk}/update-status/',
            {'status': 'IN_PROGRESS'},
            format='json',
        )
        self.assertEqual(status_change.status_code, status.HTTP_404_NOT_FOUND)
        self.other_task.refresh_from_db()
        self.assertEqual(self.other_task.status, Task.STATUS_TODO)

    def test_member_hidden_and_missing_task_comment_targets_both_return_not_found(self):
        self.client.force_authenticate(user=self.member)
        hidden = self.client.post('/api/v1/comments/', {
            'task': self.other_task.pk,
            'content': 'Hidden target',
        }, format='json')
        missing = self.client.post('/api/v1/comments/', {
            'task': 999999,
            'content': 'Missing target',
        }, format='json')
        self.assertEqual(hidden.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(hidden.status_code, missing.status_code)
        self.assertFalse(TaskComment.objects.filter(content='Hidden target').exists())

    def test_member_can_change_only_status_on_own_task(self):
        self.client.force_authenticate(user=self.member)

        retrieve = self.client.get(f'/api/v1/tasks/{self.own_task.pk}/')
        self.assertEqual(retrieve.status_code, status.HTTP_200_OK)

        mixed_update = self.client.patch(
            f'/api/v1/tasks/{self.own_task.pk}/',
            {'status': 'COMPLETED', 'title': 'Should not change'},
            format='json',
        )
        self.assertEqual(mixed_update.status_code, status.HTTP_403_FORBIDDEN)
        self.own_task.refresh_from_db()
        self.assertEqual(self.own_task.title, 'API own task')
        self.assertEqual(self.own_task.status, Task.STATUS_TODO)

        status_only = self.client.patch(
            f'/api/v1/tasks/{self.own_task.pk}/update-status/',
            {'status': 'IN_PROGRESS'},
            format='json',
        )
        self.assertEqual(status_only.status_code, status.HTTP_200_OK)
        self.assertEqual(status_only.data['status'], 'IN_PROGRESS')
        self.own_task.refresh_from_db()
        self.assertEqual(self.own_task.status, Task.STATUS_IN_PROGRESS)
        self.assertEqual(self.own_task.title, 'API own task')
        self.assertEqual(self.own_task.assigned_to_id, self.member.id)
        self.assertEqual(self.own_task.priority, Task.PRIORITY_MEDIUM)

    def test_admin_reassignment_and_status_change_send_one_assignment_notification(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.patch(
            f'/api/v1/tasks/{self.own_task.pk}/',
            {'assigned_to': self.other_member.id, 'status': 'IN_PROGRESS'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.own_task.refresh_from_db()
        self.assertEqual(self.own_task.assigned_to, self.other_member)
        notifications = self.other_member.notifications.filter(task=self.own_task)
        self.assertEqual(notifications.count(), 1)
        self.assertEqual(notifications.get().notification_type, Notification.TYPE_ASSIGNMENT)

    def test_admin_can_self_assign_and_delete_task(self):
        self.client.force_authenticate(user=self.admin)
        create = self.client.post('/api/v1/tasks/', {
            'title': 'Admin self assignment',
            'status': 'TODO',
            'priority': 'LOW',
            'assigned_to': self.admin.id,
        }, format='json')
        self.assertEqual(create.status_code, status.HTTP_201_CREATED)
        task = Task.objects.get(pk=create.data['id'])
        self.assertEqual(task.created_by, self.admin)
        self.assertEqual(task.assigned_to, self.admin)
        self.assertFalse(self.admin.notifications.filter(task=task).exists())

        deleted = self.client.delete(f'/api/v1/tasks/{task.pk}/')
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Task.objects.filter(pk=task.pk).exists())

    def test_admin_cannot_assign_inactive_user(self):
        self.other_member.is_active = False
        self.other_member.save(update_fields=['is_active'])
        self.client.force_authenticate(user=self.admin)
        response = self.client.patch(
            f'/api/v1/tasks/{self.own_task.pk}/',
            {'assigned_to': self.other_member.id},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.own_task.refresh_from_db()
        self.assertEqual(self.own_task.assigned_to, self.member)

    def test_member_can_reply_only_with_parent_from_same_task(self):
        self.client.force_authenticate(user=self.member)
        response = self.client.post('/api/v1/comments/', {
            'task': self.own_task.id,
            'parent': self.member_comment.id,
            'content': 'Valid reply',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        reply_id = response.data['id']
        self.assertEqual(TaskComment.objects.get(pk=reply_id).parent, self.member_comment)

        response = self.client.post('/api/v1/comments/', {
            'task': self.own_task.id,
            'parent': TaskComment.objects.create(
                task=self.other_task,
                author=self.other_member,
                content='Other task parent',
            ).id,
            'content': 'Cross-task reply',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(TaskComment.objects.filter(content='Cross-task reply').exists())

    def test_member_cannot_edit_another_authors_comment(self):
        self.client.force_authenticate(user=self.member)
        response = self.client.patch(
            f'/api/v1/comments/{self.admin_comment.pk}/',
            {'content': 'Edited by member'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.admin_comment.refresh_from_db()
        self.assertEqual(self.admin_comment.content, 'API admin comment')

        extra_field = self.client.patch(
            f'/api/v1/tasks/{self.own_task.pk}/update-status/',
            {'status': 'COMPLETED', 'title': 'Ignored extra', 'assigned_to': self.other_member.id},
            format='json',
        )
        self.assertEqual(extra_field.status_code, status.HTTP_200_OK)
        self.own_task.refresh_from_db()
        self.assertEqual(self.own_task.status, Task.STATUS_COMPLETED)
        self.assertEqual(self.own_task.title, 'API own task')
        self.assertEqual(self.own_task.assigned_to_id, self.member.id)

    def test_user_cannot_mark_another_users_notification_as_read(self):
        self.client.force_authenticate(user=self.member)
        response = self.client.post(
            f'/api/v1/notifications/{self.other_notification.pk}/mark-read/',
        )
        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))
        self.other_notification.refresh_from_db()
        self.assertFalse(self.other_notification.is_read)

        listed = self.client.get('/api/v1/notifications/')
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        ids = [item['id'] for item in listed.data['results']]
        self.assertNotIn(self.other_notification.pk, ids)

    def test_only_comment_author_or_admin_can_delete_comment(self):
        self.client.force_authenticate(user=self.member)
        denied = self.client.delete(f'/api/v1/comments/{self.admin_comment.pk}/')
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(TaskComment.objects.filter(pk=self.admin_comment.pk).exists())

        own = self.client.delete(f'/api/v1/comments/{self.member_comment.pk}/')
        self.assertIn(own.status_code, (status.HTTP_200_OK, status.HTTP_204_NO_CONTENT))
        self.assertFalse(TaskComment.objects.filter(pk=self.member_comment.pk).exists())

        self.client.force_authenticate(user=self.admin)
        admin_delete = self.client.delete(f'/api/v1/comments/{self.admin_comment.pk}/')
        self.assertIn(admin_delete.status_code, (status.HTTP_200_OK, status.HTTP_204_NO_CONTENT))
        self.assertFalse(TaskComment.objects.filter(pk=self.admin_comment.pk).exists())

    def test_member_cannot_access_team_management_or_analytics_endpoints(self):
        self.client.force_authenticate(user=self.member)
        self.assertEqual(
            self.client.get('/api/v1/users/').status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.get('/api/v1/analytics/overview/').status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.get('/api/v1/analytics/workload/').status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.client.force_authenticate(user=self.admin)
        self.assertEqual(self.client.get('/api/v1/users/').status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get('/api/v1/analytics/overview/').status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get('/api/v1/analytics/workload/').status_code, status.HTTP_200_OK)
