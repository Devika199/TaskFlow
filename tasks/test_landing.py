from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class LandingPageTests(TestCase):
    def setUp(self):
        self.member = User.objects.create_user(
            username='landing_member',
            email='landing_member@test.com',
            password='password123',
            role=User.ROLE_MEMBER,
        )

    def test_anonymous_get_home_returns_landing_page(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'tasks/landing.html')
        self.assertContains(response, 'TaskFlow')
        self.assertContains(response, "Bring your team's work together in one place")
        self.assertContains(response, 'Get started')
        self.assertContains(response, 'Log in')
        self.assertContains(response, reverse('register'))
        self.assertContains(response, 'id="features"')
        self.assertNotContains(response, 'password123')
        self.assertNotContains(response, 'alex.admin')

    def test_authenticated_get_home_redirects_to_dashboard(self):
        self.client.login(username='landing_member', password='password123')
        response = self.client.get('/')
        self.assertRedirects(response, reverse('dashboard'))

    def test_protected_routes_still_redirect_anonymous_users_to_login(self):
        protected = [
            reverse('dashboard'),
            reverse('task_list'),
            reverse('kanban'),
            reverse('profile'),
        ]
        for url in protected:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse('login'), response.url)
