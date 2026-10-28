from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from tasks.models import Task, TaskComment

User = get_user_model()


class ApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='api_admin',
            email='api_admin@test.com',
            password='password123',
            role=User.ROLE_ADMIN
        )
        self.member = User.objects.create_user(
            username='api_member',
            email='api_member@test.com',
            password='password123',
            role=User.ROLE_MEMBER
        )
        self.task = Task.objects.create(
            title='API Test Task',
            description='Testing REST API',
            status=Task.STATUS_TODO,
            priority=Task.PRIORITY_MEDIUM,
            created_by=self.admin,
            assigned_to=self.member
        )

    def test_unauthenticated_requests_rejected(self):
        response = self.client.get('/api/v1/tasks/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_current_user_endpoint(self):
        self.client.force_authenticate(user=self.member)
        response = self.client.get('/api/v1/auth/me/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['username'], 'api_member')
        self.assertEqual(response.data['role'], 'MEMBER')

    def test_list_tasks_and_filter(self):
        self.client.force_authenticate(user=self.member)
        response = self.client.get('/api/v1/tasks/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)

        # Filter by status
        response = self.client.get('/api/v1/tasks/?status=TODO')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['results'][0]['status'], 'TODO')

    def test_create_task_via_api(self):
        self.client.force_authenticate(user=self.admin)
        payload = {
            'title': 'Created from API',
            'description': 'REST API creation test',
            'status': 'TODO',
            'priority': 'HIGH',
            'assigned_to': self.member.id
        }
        response = self.client.post('/api/v1/tasks/', payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['title'], 'Created from API')
        self.assertEqual(response.data['created_by']['username'], 'api_admin')

    def test_kanban_update_status_action(self):
        self.client.force_authenticate(user=self.member)
        response = self.client.patch(f'/api/v1/tasks/{self.task.id}/update-status/', {
            'status': 'IN_PROGRESS'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'IN_PROGRESS')

        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'IN_PROGRESS')

    def test_add_comment_via_api(self):
        self.client.force_authenticate(user=self.member)
        response = self.client.post('/api/v1/comments/', {
            'task': self.task.id,
            'content': 'API Comment content'
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['content'], 'API Comment content')
        self.assertEqual(response.data['author']['username'], 'api_member')

    def test_analytics_overview_api(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/v1/analytics/overview/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('total_tasks', response.data)
        self.assertIn('completion_rate', response.data)
        self.assertIn('status_distribution', response.data)
