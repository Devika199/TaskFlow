from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from notifications.models import Notification
from notifications.services import create_notification
from tasks.models import Task

User = get_user_model()


class NotificationsTests(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(username='u1', email='u1@test.com', password='password123')
        self.user2 = User.objects.create_user(username='u2', email='u2@test.com', password='password123')
        self.task = Task.objects.create(title='Task for Notification', created_by=self.user1)

    def test_notification_creation_service(self):
        # Normal notification
        notif = create_notification(
            recipient=self.user2,
            actor=self.user1,
            verb="assigned a task to you",
            task=self.task,
            notification_type=Notification.TYPE_ASSIGNMENT
        )
        self.assertIsNotNone(notif)
        self.assertEqual(notif.recipient, self.user2)
        self.assertFalse(notif.is_read)

        # Self-notification should be skipped
        self_notif = create_notification(
            recipient=self.user1,
            actor=self.user1,
            verb="did something to themselves"
        )
        self.assertIsNone(self_notif)

    def test_mark_as_read_view(self):
        notif = create_notification(
            recipient=self.user2,
            actor=self.user1,
            verb="commented on your task"
        )
        self.client.login(username='u2', password='password123')

        response = self.client.post(reverse('mark_notification_read', args=[notif.id]), follow=True)
        self.assertEqual(response.status_code, 200)

        notif.refresh_from_db()
        self.assertTrue(notif.is_read)

    def test_mark_all_read_view(self):
        create_notification(recipient=self.user2, actor=self.user1, verb="Alert 1")
        create_notification(recipient=self.user2, actor=self.user1, verb="Alert 2")

        self.client.login(username='u2', password='password123')
        response = self.client.post(reverse('mark_all_notifications_read'), follow=True)
        self.assertEqual(response.status_code, 200)

        unread_count = self.user2.notifications.filter(is_read=False).count()
        self.assertEqual(unread_count, 0)

    def test_mark_read_view_requires_post(self):
        notif = create_notification(
            recipient=self.user2,
            actor=self.user1,
            verb="alerted you"
        )
        self.client.login(username='u2', password='password123')
        mark_url = reverse('mark_notification_read', args=[notif.id])

        # GET request must return 405 Method Not Allowed and not mark as read
        response = self.client.get(mark_url)
        self.assertEqual(response.status_code, 405)
        notif.refresh_from_db()
        self.assertFalse(notif.is_read)

        # POST request marks notification as read
        response = self.client.post(mark_url)
        self.assertEqual(response.status_code, 302)
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)

    def test_mark_all_read_view_requires_post(self):
        create_notification(recipient=self.user2, actor=self.user1, verb="Notice 1")
        create_notification(recipient=self.user2, actor=self.user1, verb="Notice 2")

        self.client.login(username='u2', password='password123')
        mark_all_url = reverse('mark_all_notifications_read')

        # GET request must return 405 Method Not Allowed and leave count unchanged
        response = self.client.get(mark_all_url)
        self.assertEqual(response.status_code, 405)
        self.assertEqual(self.user2.notifications.filter(is_read=False).count(), 2)

        # POST request marks all notifications as read
        response = self.client.post(mark_all_url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.user2.notifications.filter(is_read=False).count(), 0)
