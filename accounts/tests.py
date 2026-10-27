from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class AccountsTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username='admin_test',
            email='admin@test.com',
            password='password123',
            role=User.ROLE_ADMIN,
            first_name='Admin',
            last_name='User'
        )
        self.member_user = User.objects.create_user(
            username='member_test',
            email='member@test.com',
            password='password123',
            role=User.ROLE_MEMBER,
            first_name='Member',
            last_name='User'
        )

    def test_user_properties(self):
        self.assertTrue(self.admin_user.is_admin_role)
        self.assertFalse(self.member_user.is_admin_role)
        self.assertEqual(self.admin_user.initials, 'AU')
        self.assertEqual(self.admin_user.display_name, 'Admin User')

    def test_login_view(self):
        # GET login
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)

        # POST valid login
        response = self.client.post(reverse('login'), {
            'username': 'member_test',
            'password': 'password123'
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['user'].is_authenticated)

    def test_member_cannot_access_user_management(self):
        self.client.login(username='member_test', password='password123')
        response = self.client.get(reverse('user_management'))
        # Raises PermissionDenied (403)
        self.assertEqual(response.status_code, 403)

    def test_admin_can_access_user_management(self):
        self.client.login(username='admin_test', password='password123')
        response = self.client.get(reverse('user_management'))
        self.assertEqual(response.status_code, 200)

    def test_user_registration(self):
        response = self.client.post(reverse('register'), {
            'username': 'newuser',
            'email': 'newuser@test.com',
            'first_name': 'New',
            'last_name': 'Guy',
            'role': User.ROLE_MEMBER,
            'department': 'Eng',
            'job_title': 'Dev',
            'password': 'password123',
            'confirm_password': 'password123',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(username='newuser').exists())
