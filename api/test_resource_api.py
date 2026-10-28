from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework import status
from rest_framework.test import APIClient

from tasks.models import Label, Project, Task, TaskChecklistItem

User = get_user_model()


class APIResourceTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username='resource_admin',
            password='password123',
            role=User.ROLE_ADMIN,
        )
        self.member = User.objects.create_user(
            username='resource_member',
            password='password123',
            role=User.ROLE_MEMBER,
        )
        self.other_member = User.objects.create_user(
            username='resource_other',
            password='password123',
            role=User.ROLE_MEMBER,
        )
        self.project = Project.objects.create(name='Assigned project', created_by=self.admin)
        self.hidden_project = Project.objects.create(name='Hidden project', created_by=self.admin)
        self.label = Label.objects.create(name='Urgent', color='#ff0000')
        self.task = Task.objects.create(
            title='Assigned task',
            created_by=self.admin,
            assigned_to=self.member,
            project=self.project,
        )
        self.task.labels.add(self.label)
        self.item = TaskChecklistItem.objects.create(
            task=self.task,
            title='First step',
            position=1,
        )
        self.hidden_task = Task.objects.create(
            title='Hidden task',
            created_by=self.admin,
            assigned_to=self.other_member,
            project=self.hidden_project,
        )
        self.hidden_item = TaskChecklistItem.objects.create(
            task=self.hidden_task,
            title='Hidden step',
        )

    def test_admin_can_manage_projects_and_members_only_see_projects_with_assigned_tasks(self):
        self.client.force_authenticate(user=self.admin)
        created = self.client.post('/api/v1/projects/', {
            'name': 'New project',
            'description': 'Project description',
        }, format='json')
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        project_id = created.data['id']

        updated = self.client.post(f'/api/v1/projects/{project_id}/archive/')
        self.assertEqual(updated.status_code, status.HTTP_200_OK)
        self.assertTrue(updated.data['archived'])

        self.client.force_authenticate(user=self.member)
        listed = self.client.get('/api/v1/projects/')
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual([row['id'] for row in listed.data['results']], [self.project.id])
        self.assertEqual(
            self.client.get(f'/api/v1/projects/{self.hidden_project.id}/').status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.get('/api/v1/projects/999999/').status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.post('/api/v1/projects/', {'name': 'Forbidden'}, format='json').status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_admin_can_manage_labels_and_members_can_only_read_them(self):
        self.client.force_authenticate(user=self.admin)
        created = self.client.post('/api/v1/labels/', {
            'name': 'Review',
            'color': '#aabbcc',
        }, format='json')
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        label_id = created.data['id']

        invalid_color = self.client.post('/api/v1/labels/', {
            'name': 'Invalid color',
            'color': 'red',
        }, format='json')
        self.assertEqual(invalid_color.status_code, status.HTTP_400_BAD_REQUEST)
        updated = self.client.patch(
            f'/api/v1/labels/{label_id}/',
            {'color': '#112233'},
            format='json',
        )
        self.assertEqual(updated.status_code, status.HTTP_200_OK)
        self.assertEqual(updated.data['color'], '#112233')

        self.client.force_authenticate(user=self.member)
        self.assertEqual(self.client.get('/api/v1/labels/').status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.client.post('/api/v1/labels/', {'name': 'Forbidden'}, format='json').status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.patch(f'/api/v1/labels/{label_id}/', {'name': 'Changed'}).status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.client.force_authenticate(user=self.admin)
        self.assertEqual(
            self.client.delete(f'/api/v1/labels/{label_id}/').status_code,
            status.HTTP_204_NO_CONTENT,
        )

    def test_admin_can_assign_project_and_labels_to_task(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post('/api/v1/tasks/', {
            'title': 'Task with resources',
            'project': self.project.id,
            'labels': [self.label.id],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        task = Task.objects.get(pk=response.data['id'])
        self.assertEqual(task.project, self.project)
        self.assertEqual(list(task.labels.all()), [self.label])
        self.assertEqual(response.data['project'], self.project.id)
        self.assertEqual(response.data['labels'], [self.label.id])
        self.assertEqual(response.data['checklist_items'], [])

        updated = self.client.patch(
            f'/api/v1/tasks/{task.id}/',
            {'project': None, 'labels': []},
            format='json',
        )
        self.assertEqual(updated.status_code, status.HTTP_200_OK)
        task.refresh_from_db()
        self.assertIsNone(task.project)
        self.assertFalse(task.labels.exists())

    def test_archived_project_cannot_be_assigned_to_new_task_but_existing_links_remain(self):
        self.client.force_authenticate(user=self.admin)
        self.project.archived = True
        self.project.save(update_fields=['archived'])

        rejected = self.client.post('/api/v1/tasks/', {
            'title': 'New archived project task',
            'project': self.project.id,
        }, format='json')
        self.assertEqual(rejected.status_code, status.HTTP_400_BAD_REQUEST)

        existing = self.client.patch(
            f'/api/v1/tasks/{self.task.id}/',
            {'description': 'Still linked'},
            format='json',
        )
        self.assertEqual(existing.status_code, status.HTTP_200_OK)
        self.task.refresh_from_db()
        self.assertEqual(self.task.project, self.project)

    def test_checklist_admin_crud_member_completion_and_hidden_item_404(self):
        self.client.force_authenticate(user=self.admin)
        created = self.client.post('/api/v1/checklist-items/', {
            'task': self.task.id,
            'title': 'Second step',
            'position': 2,
        }, format='json')
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        created_id = created.data['id']
        updated = self.client.patch(
            f'/api/v1/checklist-items/{created_id}/',
            {'title': 'Renamed step', 'position': 3},
            format='json',
        )
        self.assertEqual(updated.status_code, status.HTTP_200_OK)
        self.assertEqual(updated.data['title'], 'Renamed step')
        self.assertEqual(updated.data['position'], 3)

        self.client.force_authenticate(user=self.member)
        listed = self.client.get('/api/v1/checklist-items/')
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        visible_ids = [row['id'] for row in listed.data['results']]
        self.assertIn(self.item.id, visible_ids)
        self.assertNotIn(self.hidden_item.id, visible_ids)
        completed = self.client.patch(
            f'/api/v1/checklist-items/{self.item.id}/',
            {'is_completed': True},
            format='json',
        )
        self.assertEqual(completed.status_code, status.HTTP_200_OK)
        self.item.refresh_from_db()
        self.assertTrue(self.item.is_completed)

        denied = self.client.patch(
            f'/api/v1/checklist-items/{self.item.id}/',
            {'is_completed': False, 'title': 'Not allowed'},
            format='json',
        )
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)
        self.item.refresh_from_db()
        self.assertEqual(self.item.title, 'First step')
        self.assertTrue(self.item.is_completed)
        self.assertEqual(
            self.client.post('/api/v1/checklist-items/', {
                'task': self.task.id,
                'title': 'Not allowed',
            }, format='json').status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post('/api/v1/checklist-items/', {
                'task': self.hidden_task.id,
                'title': 'Hidden',
            }, format='json').status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.post('/api/v1/checklist-items/', {
                'task': 999999,
                'title': 'Missing',
            }, format='json').status_code,
            status.HTTP_404_NOT_FOUND,
        )

        hidden = self.client.get(f'/api/v1/checklist-items/{self.hidden_item.id}/')
        missing = self.client.get('/api/v1/checklist-items/999999/')
        self.assertEqual(hidden.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(hidden.status_code, missing.status_code)
        self.assertEqual(
            self.client.get(f'/api/v1/tasks/{self.hidden_task.id}/').status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.get(f'/api/v1/checklist-items/?task={self.hidden_task.id}').status_code,
            status.HTTP_404_NOT_FOUND,
        )

        self.client.force_authenticate(user=self.admin)
        self.assertEqual(
            self.client.delete(f'/api/v1/checklist-items/{created_id}/').status_code,
            status.HTTP_204_NO_CONTENT,
        )

    def test_task_list_prefetches_related_resources_without_per_task_queries(self):
        self.client.force_authenticate(user=self.admin)

        with CaptureQueriesContext(connection) as initial_queries:
            initial_response = self.client.get('/api/v1/tasks/')
        self.assertEqual(initial_response.status_code, status.HTTP_200_OK)

        for index in range(3):
            task = Task.objects.create(
                title=f'Extra task {index}',
                created_by=self.admin,
                assigned_to=self.member,
                project=self.project,
            )
            task.labels.add(self.label)
            TaskChecklistItem.objects.create(task=task, title=f'Step {index}')

        with CaptureQueriesContext(connection) as expanded_queries:
            response = self.client.get('/api/v1/tasks/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertLessEqual(len(expanded_queries), len(initial_queries) + 1)
        rows = response.data['results']
        self.assertTrue(all('project' in row and 'labels' in row and 'checklist_items' in row for row in rows))
        self.assertEqual(rows[0]['project'], self.project.id)
        self.assertEqual(rows[0]['labels'], [self.label.id])
        self.assertEqual(len(rows[0]['checklist_items']), 1)
