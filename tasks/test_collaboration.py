from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from tasks.forms import LabelForm, TaskForm
from tasks.models import Label, Project, Task, TaskActivityLog, TaskChecklistItem

User = get_user_model()


class TaskCollaborationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='collab_admin',
            email='collab-admin@example.com',
            password='password123',
            role=User.ROLE_ADMIN,
        )
        self.member = User.objects.create_user(
            username='collab_member',
            email='collab-member@example.com',
            password='password123',
            role=User.ROLE_MEMBER,
        )
        self.other_member = User.objects.create_user(
            username='collab_other',
            email='collab-other@example.com',
            password='password123',
            role=User.ROLE_MEMBER,
        )
        self.project = Project.objects.create(name='Launch', created_by=self.admin)
        self.other_project = Project.objects.create(name='Internal', created_by=self.admin)
        self.label = Label.objects.create(name='Design', color='#2563eb')
        self.task = Task.objects.create(
            title='Prepare launch',
            status=Task.STATUS_TODO,
            priority=Task.PRIORITY_HIGH,
            due_date=timezone.localdate() + timedelta(days=2),
            created_by=self.admin,
            assigned_to=self.member,
            project=self.project,
        )
        self.task.labels.add(self.label)
        self.other_task = Task.objects.create(
            title='Private task',
            created_by=self.admin,
            assigned_to=self.other_member,
            project=self.other_project,
        )

    def test_member_can_toggle_only_assigned_task_checklist_item(self):
        item = TaskChecklistItem.objects.create(task=self.task, title='Review designs')
        self.client.login(username='collab_member', password='password123')

        response = self.client.post(reverse('checklist_toggle', args=[self.task.pk, item.pk]))

        self.assertRedirects(response, reverse('task_detail', args=[self.task.pk]))
        item.refresh_from_db()
        self.task.refresh_from_db()
        self.assertTrue(item.is_completed)
        self.assertEqual(self.task.status, Task.STATUS_TODO)
        self.assertEqual(self.task.checklist_completed, 1)
        self.assertEqual(self.task.checklist_total, 1)
        self.assertTrue(TaskActivityLog.objects.filter(
            task=self.task,
            actor=self.member,
            action='CHECKLIST_UPDATED',
        ).exists())

        other_item = TaskChecklistItem.objects.create(task=self.other_task, title='Secret item')
        response = self.client.post(reverse('checklist_toggle', args=[self.other_task.pk, other_item.pk]))
        self.assertEqual(response.status_code, 404)
        other_item.refresh_from_db()
        self.assertFalse(other_item.is_completed)

    def test_member_cannot_manage_checklist_items(self):
        self.client.login(username='collab_member', password='password123')
        response = self.client.post(reverse('checklist_add', args=[self.task.pk]), {'title': 'Unauthorized'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(TaskChecklistItem.objects.filter(title='Unauthorized').exists())

    def test_admin_can_create_edit_reorder_and_delete_checklist_items(self):
        self.client.login(username='collab_admin', password='password123')
        first = TaskChecklistItem.objects.create(task=self.task, title='First', position=0)
        second = TaskChecklistItem.objects.create(task=self.task, title='Second', position=1)

        response = self.client.post(reverse('checklist_reorder', args=[self.task.pk, second.pk]), {'direction': 'up'})
        self.assertRedirects(response, reverse('task_detail', args=[self.task.pk]))
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(second.position, 0)
        self.assertEqual(first.position, 1)

        response = self.client.post(reverse('checklist_edit', args=[self.task.pk, second.pk]), {'title': 'Revised'})
        self.assertRedirects(response, reverse('task_detail', args=[self.task.pk]))
        second.refresh_from_db()
        self.assertEqual(second.title, 'Revised')

        response = self.client.post(reverse('checklist_add', args=[self.task.pk]), {'title': 'Third'})
        self.assertRedirects(response, reverse('task_detail', args=[self.task.pk]))
        self.assertTrue(TaskChecklistItem.objects.filter(task=self.task, title='Third').exists())

        response = self.client.post(reverse('checklist_delete', args=[self.task.pk, first.pk]))
        self.assertRedirects(response, reverse('task_detail', args=[self.task.pk]))
        self.assertFalse(TaskChecklistItem.objects.filter(pk=first.pk).exists())

    def test_task_form_saves_optional_project_and_labels(self):
        form = TaskForm(data={
            'title': 'Assigned project task',
            'description': 'Context',
            'status': Task.STATUS_TODO,
            'priority': Task.PRIORITY_MEDIUM,
            'due_date': '',
            'assigned_to': self.member.pk,
            'project': self.project.pk,
            'labels': [self.label.pk],
        })
        self.assertTrue(form.is_valid(), form.errors)
        task = form.save(commit=False)
        task.created_by = self.admin
        task.save()
        form.save_m2m()
        self.assertEqual(task.project, self.project)
        self.assertEqual(list(task.labels.all()), [self.label])

    def test_admin_task_create_view_persists_project_and_multiple_labels(self):
        second_label = Label.objects.create(name='Launch', color='#9333ea')
        self.client.login(username='collab_admin', password='password123')

        response = self.client.post(reverse('task_create'), {
            'title': 'Task created in a project',
            'description': 'Task form relation persistence',
            'status': Task.STATUS_TODO,
            'priority': Task.PRIORITY_MEDIUM,
            'due_date': '',
            'assigned_to': self.member.pk,
            'project': self.project.pk,
            'labels': [self.label.pk, second_label.pk],
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        task = Task.objects.get(title='Task created in a project')
        self.assertEqual(task.project, self.project)
        self.assertEqual(set(task.labels.all()), {self.label, second_label})

    def test_archived_project_cannot_be_assigned_to_new_task(self):
        self.project.archived = True
        self.project.save(update_fields=['archived'])
        form = TaskForm(data={
            'title': 'Archived project task',
            'status': Task.STATUS_TODO,
            'priority': Task.PRIORITY_LOW,
            'project': self.project.pk,
            'labels': [],
        })
        self.assertFalse(form.is_valid())
        self.assertIn('project', form.errors)

    def test_member_filters_to_own_project_and_label_tasks(self):
        self.client.login(username='collab_member', password='password123')
        response = self.client.get(reverse('task_list'), {
            'project': self.project.pk,
            'label': self.label.pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.task.title)
        self.assertNotContains(response, self.other_task.title)
        self.assertContains(response, 'value="%s" selected' % self.project.pk)
        self.assertContains(response, 'value="%s" selected' % self.label.pk)
        self.assertEqual(list(response.context['projects']), [self.project])

    def test_task_list_and_kanban_preload_related_collaboration_data(self):
        self.client.login(username='collab_admin', password='password123')
        urls = [reverse('task_list'), reverse('kanban')]
        for url in urls:
            with self.subTest(url=url):
                with CaptureQueriesContext(connection) as initial_queries:
                    initial_response = self.client.get(url)
                self.assertEqual(initial_response.status_code, 200)

                for index in range(3):
                    task = Task.objects.create(
                        title=f'Additional task {index}',
                        created_by=self.admin,
                        assigned_to=self.member,
                        project=self.project,
                    )
                    task.labels.add(self.label)
                    TaskChecklistItem.objects.create(task=task, title=f'Checklist {index}')

                with CaptureQueriesContext(connection) as expanded_queries:
                    expanded_response = self.client.get(url)
                self.assertEqual(expanded_response.status_code, 200)
                self.assertLessEqual(len(expanded_queries), len(initial_queries) + 1)

    def test_admin_can_manage_projects_and_labels(self):
        self.client.login(username='collab_admin', password='password123')
        response = self.client.post(reverse('projects'), {'name': 'New project', 'description': 'Roadmap'})
        self.assertRedirects(response, reverse('projects'))
        project = Project.objects.get(name='New project')

        response = self.client.post(reverse('project_archive', args=[project.pk]))
        self.assertRedirects(response, reverse('projects'))
        project.refresh_from_db()
        self.assertTrue(project.archived)

        response = self.client.post(reverse('labels'), {'name': 'QA', 'color': '#16a34a'})
        self.assertRedirects(response, reverse('labels'))
        label = Label.objects.get(name='QA')
        response = self.client.post(reverse('label_edit', args=[label.pk]), {
            'name': 'Quality',
            'color': '#16a34a',
        })
        self.assertRedirects(response, reverse('labels'))
        self.assertTrue(Label.objects.filter(pk=label.pk, name='Quality').exists())
        response = self.client.post(reverse('label_delete', args=[label.pk]))
        self.assertRedirects(response, reverse('labels'))
        self.assertFalse(Label.objects.filter(pk=label.pk).exists())

    def test_member_cannot_manage_projects_or_labels(self):
        self.client.login(username='collab_member', password='password123')
        self.assertEqual(self.client.get(reverse('projects')).status_code, 403)
        self.assertEqual(self.client.get(reverse('labels')).status_code, 403)
        self.assertEqual(
            self.client.post(reverse('projects'), {'name': 'Nope'}).status_code,
            403,
        )

    def test_label_form_rejects_invalid_hex_color_and_duplicate_name(self):
        invalid_color = LabelForm(data={'name': 'Bad color', 'color': 'blue'})
        self.assertFalse(invalid_color.is_valid())
        self.assertIn('color', invalid_color.errors)

        duplicate = LabelForm(data={'name': 'design', 'color': '#abcdef'})
        self.assertFalse(duplicate.is_valid())
        self.assertIn('name', duplicate.errors)
