import csv
import io
import json
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from notifications.models import Notification
from organizations.models import Organization, OrganizationMembership
from tasks.models import Label, Project, Task, TaskActivityLog

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

    @patch('django.utils.timezone.localdate', return_value=date(2026, 10, 28))
    def test_calendar_scopes_members_and_admins_and_supports_admin_assignee_filter(self, mock_localdate):
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


class TaskCalendarRescheduleTests(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="Org A", slug="org-a")
        self.org_b = Organization.objects.create(name="Org B", slug="org-b")

        self.admin = User.objects.create_user(
            username='reschedule_admin',
            email='admin@example.com',
            password='password123',
            role=User.ROLE_ADMIN,
        )
        self.member = User.objects.create_user(
            username='reschedule_member',
            email='member@example.com',
            password='password123',
            role=User.ROLE_MEMBER,
        )
        self.outsider = User.objects.create_user(
            username='reschedule_outsider',
            email='outsider@example.com',
            password='password123',
            role=User.ROLE_ADMIN,
        )

        OrganizationMembership.objects.create(
            organization=self.org_a,
            user=self.admin,
            role=OrganizationMembership.ROLE_ADMIN,
            is_active=True,
        )
        OrganizationMembership.objects.create(
            organization=self.org_a,
            user=self.member,
            role=OrganizationMembership.ROLE_MEMBER,
            is_active=True,
        )
        OrganizationMembership.objects.create(
            organization=self.org_b,
            user=self.outsider,
            role=OrganizationMembership.ROLE_ADMIN,
            is_active=True,
        )

        self.project = Project.objects.create(
            name="Alpha Project",
            organization=self.org_a,
            created_by=self.admin,
        )

        self.task = Task.objects.create(
            organization=self.org_a,
            title='Sprint Planning Task',
            description='Plan the sprint',
            priority=Task.PRIORITY_HIGH,
            status=Task.STATUS_TODO,
            due_date=date(2026, 10, 28),
            project=self.project,
            created_by=self.admin,
            assigned_to=self.member,
        )

        self.task_b = Task.objects.create(
            organization=self.org_b,
            title='Beta Project Task',
            description='Beta task',
            priority=Task.PRIORITY_MEDIUM,
            status=Task.STATUS_TODO,
            due_date=date(2026, 10, 28),
            created_by=self.outsider,
            assigned_to=self.outsider,
        )

    def test_reschedule_task_success_json(self):
        self.client.login(username='reschedule_admin', password='password123')
        url = reverse('reschedule_task', args=[self.task.pk])
        response = self.client.post(
            url,
            data=json.dumps({'due_date': '2026-11-15'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['id'], self.task.pk)
        self.assertEqual(data['due_date'], '2026-11-15')
        self.assertIn('rescheduled to', data['message'].lower())

        self.task.refresh_from_db()
        self.assertEqual(self.task.due_date, date(2026, 11, 15))

        # Activity log created
        log = TaskActivityLog.objects.filter(task=self.task, action='UPDATED').first()
        self.assertIsNotNone(log)
        self.assertIn('2026-11-15', log.details)

        # Notification sent to assignee (since actor was admin != assignee)
        notif = Notification.objects.filter(recipient=self.member, task=self.task).first()
        self.assertIsNotNone(notif)
        self.assertIn('rescheduled', notif.verb)

    def test_reschedule_task_clear_due_date(self):
        self.client.login(username='reschedule_admin', password='password123')
        url = reverse('reschedule_task', args=[self.task.pk])
        response = self.client.post(
            url,
            data=json.dumps({'due_date': None}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIsNone(data['due_date'])
        self.assertEqual(data['due_status'], 'none')

        self.task.refresh_from_db()
        self.assertIsNone(self.task.due_date)

    def test_reschedule_task_form_post(self):
        self.client.login(username='reschedule_admin', password='password123')
        url = reverse('reschedule_task', args=[self.task.pk])
        response = self.client.post(
            url,
            data={'due_date': '2026-12-01'},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['due_date'], '2026-12-01')

        self.task.refresh_from_db()
        self.assertEqual(self.task.due_date, date(2026, 12, 1))

    def test_reschedule_task_invalid_date_format(self):
        self.client.login(username='reschedule_admin', password='password123')
        url = reverse('reschedule_task', args=[self.task.pk])
        response = self.client.post(
            url,
            data=json.dumps({'due_date': 'not-a-date'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data.get('error'), 'Invalid date format. Expected YYYY-MM-DD.')

        # Ensure task due date was not changed
        self.task.refresh_from_db()
        self.assertEqual(self.task.due_date, date(2026, 10, 28))

    def test_reschedule_task_rejects_get_method(self):
        self.client.login(username='reschedule_admin', password='password123')
        url = reverse('reschedule_task', args=[self.task.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)

    def test_reschedule_task_unauthenticated(self):
        url = reverse('reschedule_task', args=[self.task.pk])
        response = self.client.post(
            url,
            data=json.dumps({'due_date': '2026-11-20'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 302)

    def test_reschedule_task_member_without_edit_permission_rejected(self):
        self.client.login(username='reschedule_member', password='password123')
        url = reverse('reschedule_task', args=[self.task.pk])
        response = self.client.post(
            url,
            data=json.dumps({'due_date': '2026-11-20'}),
            content_type='application/json',
        )
        # Non-admin member cannot edit task -> 403 Forbidden
        self.assertEqual(response.status_code, 403)

        self.task.refresh_from_db()
        self.assertEqual(self.task.due_date, date(2026, 10, 28))

    def test_reschedule_task_cross_tenant_rejected(self):
        # Admin of Org B tries to reschedule task of Org A
        self.client.login(username='reschedule_outsider', password='password123')
        url = reverse('reschedule_task', args=[self.task.pk])
        response = self.client.post(
            url,
            data=json.dumps({'due_date': '2026-11-20'}),
            content_type='application/json',
        )
        # Org isolation returns 404
        self.assertEqual(response.status_code, 404)

    def test_calendar_week_and_day_views(self):
        self.client.login(username='reschedule_admin', password='password123')

        # Week view test
        response_week = self.client.get(reverse('task_calendar'), {
            'view': 'week',
            'date': '2026-10-28',
        })
        self.assertEqual(response_week.status_code, 200)
        self.assertEqual(response_week.context['current_view'], 'week')
        self.assertEqual(response_week.context['current_date'], '2026-10-28')
        self.assertEqual(len(response_week.context['week_days']), 7)
        self.assertContains(response_week, self.task.title)
        # Week view UI redesign structure
        self.assertContains(response_week, 'calendar-week-board-wrapper')
        self.assertContains(response_week, 'calendar-week-grid')
        self.assertContains(response_week, 'calendar-week-col')
        self.assertContains(response_week, 'calendar-week-col-header')
        self.assertContains(response_week, 'calendar-week-weekday')
        self.assertContains(response_week, 'calendar-week-day-number')
        self.assertContains(response_week, 'badge-priority-high')
        self.assertContains(response_week, 'badge-status-todo')
        self.assertContains(response_week, 'calendar-week-empty-slot')
        self.assertContains(response_week, 'calendar-drag-handle')
        self.assertContains(response_week, f'data-reschedule-url="{reverse("reschedule_task", args=[self.task.pk])}"')

        # Day view test
        response_day = self.client.get(reverse('task_calendar'), {
            'view': 'day',
            'date': '2026-10-28',
        })
        self.assertEqual(response_day.status_code, 200)
        self.assertEqual(response_day.context['current_view'], 'day')
        self.assertEqual(response_day.context['current_date'], '2026-10-28')
        self.assertIn(self.task, response_day.context['day_tasks'])
        self.assertContains(response_day, self.task.title)

    def test_calendar_filtering_by_status_priority_project(self):
        self.client.login(username='reschedule_admin', password='password123')

        # Status match
        resp_todo = self.client.get(reverse('task_calendar'), {
            'month': '2026-10',
            'status': 'todo',
        })
        self.assertContains(resp_todo, self.task.title)

        resp_completed = self.client.get(reverse('task_calendar'), {
            'month': '2026-10',
            'status': 'completed',
        })
        self.assertNotContains(resp_completed, self.task.title)

        # Priority match
        resp_high = self.client.get(reverse('task_calendar'), {
            'month': '2026-10',
            'priority': 'high',
        })
        self.assertContains(resp_high, self.task.title)

        resp_low = self.client.get(reverse('task_calendar'), {
            'month': '2026-10',
            'priority': 'low',
        })
        self.assertNotContains(resp_low, self.task.title)

        # Project match
        resp_proj = self.client.get(reverse('task_calendar'), {
            'month': '2026-10',
            'project': self.project.id,
        })
        self.assertContains(resp_proj, self.task.title)

    def test_calendar_ui_view_switcher_and_navigation_preserves_filters(self):
        self.client.login(username='reschedule_admin', password='password123')

        # Month view active
        resp_month = self.client.get(reverse('task_calendar'), {
            'view': 'month',
            'month': '2026-10',
            'status': 'todo',
        })
        self.assertEqual(resp_month.status_code, 200)
        # Check active view button
        self.assertContains(resp_month, 'view=month&amp;month=2026-10&amp;status=TODO')
        self.assertContains(resp_month, 'view=week&amp;date=2026-10-01&amp;status=TODO')
        self.assertContains(resp_month, 'view=day&amp;date=2026-10-01&amp;status=TODO')
        # Check Clear filter link appears
        self.assertContains(resp_month, 'Clear')

        # Week view active
        resp_week = self.client.get(reverse('task_calendar'), {
            'view': 'week',
            'date': '2026-10-28',
            'status': 'todo',
        })
        self.assertEqual(resp_week.status_code, 200)
        self.assertContains(resp_week, 'view=week&amp;date=2026-10-28&amp;status=TODO')
        self.assertContains(resp_week, 'view=week&amp;date=2026-10-19&amp;status=TODO')  # prev week
        self.assertContains(resp_week, 'view=week&amp;date=2026-11-02&amp;status=TODO')  # next week

        # Day view active
        resp_day = self.client.get(reverse('task_calendar'), {
            'view': 'day',
            'date': '2026-10-28',
            'status': 'todo',
        })
        self.assertEqual(resp_day.status_code, 200)
        self.assertContains(resp_day, 'view=day&amp;date=2026-10-27&amp;status=TODO')  # prev day
        self.assertContains(resp_day, 'view=day&amp;date=2026-10-29&amp;status=TODO')  # next day

    def test_calendar_ui_day_view_empty_state(self):
        self.client.login(username='reschedule_admin', password='password123')
        # Request a day with no tasks
        resp_empty_day = self.client.get(reverse('task_calendar'), {
            'view': 'day',
            'date': '2026-11-20',
        })
        self.assertEqual(resp_empty_day.status_code, 200)
        self.assertContains(resp_empty_day, 'No tasks scheduled')
        self.assertContains(resp_empty_day, 'Create New Task')

    def test_calendar_ui_assignee_filter_role_visibility(self):
        # Admin can filter by assignee
        self.client.login(username='reschedule_admin', password='password123')
        resp_admin = self.client.get(reverse('task_calendar'))
        self.assertContains(resp_admin, 'id="calendarAssignee"')

        # Regular member cannot filter by assignee
        self.client.login(username='reschedule_member', password='password123')
        resp_member = self.client.get(reverse('task_calendar'))
        self.assertNotContains(resp_member, 'id="calendarAssignee"')

    def test_calendar_drag_and_drop_markup_for_admin(self):
        self.client.login(username='reschedule_admin', password='password123')
        response = self.client.get(reverse('task_calendar'), {
            'view': 'month',
            'month': '2026-10',
        })
        self.assertEqual(response.status_code, 200)
        # Dropzones rendered with data-calendar-dropzone and ISO date
        self.assertContains(response, 'data-calendar-dropzone="true"')
        self.assertContains(response, 'data-date="2026-10-28"')
        # Task has edit permission, drag handle, and reschedule URL
        self.assertContains(response, 'data-can-edit="true"')
        self.assertContains(response, 'class="calendar-drag-handle"')
        self.assertContains(response, f'data-reschedule-url="{reverse("reschedule_task", args=[self.task.pk])}"')
        # Script included
        self.assertContains(response, 'js/calendar.js')

    def test_calendar_drag_and_drop_markup_for_member(self):
        self.client.login(username='reschedule_member', password='password123')
        response = self.client.get(reverse('task_calendar'), {
            'view': 'month',
            'month': '2026-10',
        })
        self.assertEqual(response.status_code, 200)
        # Non-admin member cannot edit -> data-can-edit="false", no drag handles
        self.assertContains(response, 'data-can-edit="false"')
        self.assertNotContains(response, 'class="calendar-drag-handle"')
        # But task detail link remains functional
        self.assertContains(response, reverse('task_detail', args=[self.task.pk]))

