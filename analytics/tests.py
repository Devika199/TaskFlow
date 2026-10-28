from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tasks.models import Task

User = get_user_model()


class MyAnalyticsTests(TestCase):
    def setUp(self):
        self.member = User.objects.create_user(
            username='analytics_member',
            email='analytics_member@test.com',
            password='password123',
            role=User.ROLE_MEMBER,
        )
        self.other_member = User.objects.create_user(
            username='analytics_other',
            email='analytics_other@test.com',
            password='password123',
            role=User.ROLE_MEMBER,
        )
        self.admin = User.objects.create_user(
            username='analytics_admin',
            email='analytics_admin@test.com',
            password='password123',
            role=User.ROLE_ADMIN,
        )

    def create_task(self, title, assignee, **kwargs):
        return Task.objects.create(
            title=title,
            created_by=self.admin,
            assigned_to=assignee,
            **kwargs,
        )

    def test_member_sees_only_own_task_metrics_and_urgent_tasks(self):
        today = timezone.localdate()
        completed = self.create_task(
            'My completed task',
            self.member,
            status=Task.STATUS_COMPLETED,
            priority=Task.PRIORITY_HIGH,
        )
        Task.objects.filter(pk=completed.pk).update(
            completed_at=timezone.now() - timedelta(days=14),
        )
        self.create_task(
            'My due today task',
            self.member,
            due_date=today,
            status=Task.STATUS_IN_PROGRESS,
            priority=Task.PRIORITY_MEDIUM,
        )
        self.create_task(
            'My due soon task',
            self.member,
            due_date=today + timedelta(days=2),
            status=Task.STATUS_TODO,
            priority=Task.PRIORITY_MEDIUM,
        )
        self.create_task(
            'My overdue task',
            self.member,
            due_date=today - timedelta(days=1),
            status=Task.STATUS_TODO,
            priority=Task.PRIORITY_LOW,
        )
        self.create_task(
            'My unscheduled task',
            self.member,
            status=Task.STATUS_TODO,
            priority=Task.PRIORITY_LOW,
        )
        self.create_task(
            'Other member completed task',
            self.other_member,
            status=Task.STATUS_COMPLETED,
            priority=Task.PRIORITY_HIGH,
        )
        self.create_task(
            'Other member urgent task',
            self.other_member,
            due_date=today - timedelta(days=2),
            status=Task.STATUS_IN_PROGRESS,
            priority=Task.PRIORITY_HIGH,
        )

        self.client.login(username='analytics_member', password='password123')
        response = self.client.get(reverse('my_analytics'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_tasks'], 5)
        self.assertEqual(response.context['completed_tasks'], 1)
        self.assertEqual(response.context['in_progress_tasks'], 1)
        self.assertEqual(response.context['todo_tasks'], 3)
        self.assertEqual(response.context['overdue_tasks'], 1)
        self.assertEqual(response.context['due_today_tasks'], 1)
        self.assertEqual(response.context['due_soon_tasks'], 1)
        self.assertEqual(response.context['completion_rate'], 20.0)
        self.assertEqual(
            response.context['priority_distribution'],
            {'High': 1, 'Medium': 2, 'Low': 2},
        )
        self.assertEqual(sum(response.context['chart_data']['weekly']['values']), 1)
        self.assertContains(response, 'My overdue task')
        self.assertNotContains(response, 'Other member urgent task')
        self.assertNotContains(response, 'Other member completed task')

    def test_admin_using_my_analytics_sees_only_their_own_tasks(self):
        self.create_task(
            'Admin personal task',
            self.admin,
            status=Task.STATUS_COMPLETED,
        )
        self.create_task(
            'Member task hidden from admin personal analytics',
            self.member,
            status=Task.STATUS_TODO,
        )

        self.client.login(username='analytics_admin', password='password123')
        response = self.client.get(reverse('my_analytics'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_tasks'], 1)
        self.assertEqual(response.context['completed_tasks'], 1)
        self.assertNotContains(response, 'Member task hidden from admin personal analytics')

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse('my_analytics'))
        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('my_analytics')}",
        )

    def test_member_dashboard_and_api_analytics_remain_forbidden(self):
        self.client.login(username='analytics_member', password='password123')

        self.assertEqual(self.client.get(reverse('analytics_dashboard')).status_code, 403)
        self.assertEqual(
            self.client.get('/api/v1/analytics/overview/').status_code,
            403,
        )

    def test_zero_tasks_render_an_empty_state_and_zero_completion_rate(self):
        self.client.login(username='analytics_member', password='password123')

        response = self.client.get(reverse('my_analytics'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_tasks'], 0)
        self.assertEqual(response.context['completion_rate'], 0)
        self.assertContains(response, 'No assigned tasks yet')

    def test_sidebar_analytics_link_is_scoped_to_user_role(self):
        self.client.login(username='analytics_member', password='password123')
        member_response = self.client.get(reverse('dashboard'))
        self.assertContains(member_response, reverse('my_analytics'))
        self.assertContains(member_response, 'My Analytics')
        self.assertNotContains(member_response, 'Workload &amp; Metrics')

        self.client.logout()
        self.client.login(username='analytics_admin', password='password123')
        admin_response = self.client.get(reverse('dashboard'))
        self.assertContains(admin_response, reverse('analytics_dashboard'))
        self.assertContains(admin_response, 'Workload &amp; Metrics')
        self.assertNotContains(admin_response, 'My Analytics')

    @override_settings(DEBUG=False)
    def test_403_page_uses_access_denied_template_and_keeps_status(self):
        self.client.login(username='analytics_member', password='password123')

        response = self.client.get(reverse('analytics_dashboard'))

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, 'Access denied', status_code=403)
        self.assertContains(response, 'Back to dashboard', status_code=403)
