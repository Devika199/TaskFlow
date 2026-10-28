import csv
import io
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from tasks.models import Label, Project, Task

User = get_user_model()


class CalendarPaletteExportTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='calendar_admin',
            email='calendar-admin@example.com',
            password='password123',
            role=User.ROLE_ADMIN,
        )
        self.member = User.objects.create_user(
            username='calendar_member',
            email='calendar-member@example.com',
            password='password123',
            role=User.ROLE_MEMBER,
        )
        self.other_member = User.objects.create_user(
            username='calendar_other',
            email='calendar-other@example.com',
            password='password123',
            role=User.ROLE_MEMBER,
        )
        self.own_task = Task.objects.create(
            title='Palette confidential-code own',
            description='shared-search marker',
            priority=Task.PRIORITY_HIGH,
            due_date=date(2026, 10, 28),
            created_by=self.admin,
            assigned_to=self.member,
        )
        self.other_task = Task.objects.create(
            title='Palette confidential-code other',
            description='shared-search marker',
            priority=Task.PRIORITY_LOW,
            due_date=date(2026, 10, 28),
            created_by=self.admin,
            assigned_to=self.other_member,
        )

    def test_calendar_scopes_members_and_admins_and_supports_admin_assignee_filter(self):
        self.client.login(username='calendar_member', password='password123')
        response = self.client.get(reverse('task_calendar'), {'month': '2026-10'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.own_task.title)
        self.assertNotContains(response, self.other_task.title)
        self.assertContains(response, 'priority-high')
        self.assertContains(response, 'is-today')

        self.client.login(username='calendar_admin', password='password123')
        response = self.client.get(reverse('task_calendar'), {'month': '2026-10'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.own_task.title)
        self.assertContains(response, self.other_task.title)
        filtered = self.client.get(reverse('task_calendar'), {
            'month': '2026-10',
            'assigned_to': self.member.pk,
        })
        self.assertContains(filtered, self.own_task.title)
        self.assertNotContains(filtered, self.other_task.title)

    def test_palette_search_never_returns_another_members_tasks(self):
        self.client.login(username='calendar_member', password='password123')
        response = self.client.get(reverse('task_palette_search'), {'q': 'shared-search'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [result['id'] for result in response.json()['results']],
            [self.own_task.pk],
        )

        self.client.login(username='calendar_admin', password='password123')
        response = self.client.get(reverse('task_palette_search'), {'q': 'shared-search'})
        self.assertEqual(
            {result['id'] for result in response.json()['results']},
            {self.own_task.pk, self.other_task.pk},
        )

    def test_csv_export_is_admin_only_and_escapes_injection_cells(self):
        self.own_task.title = '=HYPERLINK("https://example.test")'
        self.own_task.description = '+SUM(1,1)'
        self.own_task.save(update_fields=['title', 'description', 'updated_at'])
        project = Project.objects.create(name='-project', created_by=self.admin)
        label = Label.objects.create(name='@label', color='#123456')
        self.own_task.project = project
        self.own_task.save(update_fields=['project', 'updated_at'])
        self.own_task.labels.add(label)

        self.client.login(username='calendar_member', password='password123')
        denied = self.client.get(reverse('task_csv_export'))
        self.assertEqual(denied.status_code, 403)

        self.client.login(username='calendar_admin', password='password123')
        response = self.client.get(reverse('task_csv_export'), {'priority': Task.PRIORITY_HIGH})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertRegex(
            response['Content-Disposition'],
            r'^attachment; filename="taskflow-tasks-\d{4}-\d{2}-\d{2}\.csv"$',
        )
        rows = list(csv.reader(io.StringIO(response.content.decode('utf-8'))))
        task_row = next(row for row in rows[1:] if row[0].endswith('HYPERLINK("https://example.test")'))
        self.assertTrue(task_row[0].startswith("'="))
        self.assertTrue(task_row[1].startswith("'+"))
        self.assertTrue(task_row[6].startswith("'-"))
        self.assertTrue(task_row[7].startswith("'@"))
        self.assertFalse(any(row[0] == self.other_task.title for row in rows[1:]))

    def test_calendar_and_palette_require_authentication(self):
        self.assertEqual(
            self.client.get(reverse('task_calendar')).status_code,
            302,
        )
        self.assertEqual(
            self.client.get(reverse('task_palette_search'), {'q': 'shared-search'}).status_code,
            302,
        )
