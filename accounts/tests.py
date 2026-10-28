from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test import override_settings
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
        self.assertContains(response, 'Welcome back')
        self.assertNotContains(response, 'password123')
        self.assertNotContains(response, 'remember_me')

        # POST valid login
        response = self.client.post(reverse('login'), {
            'username': 'member_test',
            'password': 'password123'
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['user'].is_authenticated)
        self.assertEqual(response.redirect_chain[-1][0], reverse('dashboard'))

        self.client.logout()
        response = self.client.post(reverse('login'), {
            'username': 'member@test.com',
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
        response = self.client.post(reverse('register'), self.registration_data())
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username='newuser')
        self.assertEqual(user.role, User.ROLE_MEMBER)
        self.assertTrue(user.check_password('password123'))

    def test_admin_registration_requires_configured_correct_code(self):
        registration_data = self.registration_data(role=User.ROLE_ADMIN)
        with override_settings(ADMIN_REGISTRATION_CODE=''):
            response = self.client.post(reverse('register'), registration_data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('role', response.context['form'].errors)
        self.assertFalse(User.objects.filter(username='newuser').exists())

        with override_settings(ADMIN_REGISTRATION_CODE='expected-code'):
            registration_data['admin_access_code'] = 'wrong-code'
            response = self.client.post(reverse('register'), registration_data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('admin_access_code', response.context['form'].errors)
        self.assertFalse(User.objects.filter(username='newuser').exists())

    def test_admin_registration_succeeds_with_correct_code(self):
        with override_settings(ADMIN_REGISTRATION_CODE='expected-code'):
            response = self.client.post(reverse('register'), self.registration_data(
                role=User.ROLE_ADMIN,
                admin_access_code='expected-code',
            ))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(User.objects.get(username='newuser').role, User.ROLE_ADMIN)

    def test_registration_rejects_invalid_email(self):
        response = self.client.post(reverse('register'), self.registration_data(
            email='not-an-email',
        ))
        self.assertEqual(response.status_code, 200)
        self.assertIn('email', response.context['form'].errors)
        self.assertFalse(User.objects.filter(username='newuser').exists())

    def test_registration_rejects_duplicate_email_case_insensitively(self):
        response = self.client.post(reverse('register'), self.registration_data(
            email='MEMBER@TEST.COM',
        ))
        self.assertEqual(response.status_code, 200)
        self.assertIn('email', response.context['form'].errors)
        self.assertFalse(User.objects.filter(username='newuser').exists())

    def test_registration_rejects_tampered_role(self):
        response = self.client.post(reverse('register'), self.registration_data(
            role='SUPERUSER',
        ))
        self.assertEqual(response.status_code, 200)
        self.assertIn('role', response.context['form'].errors)
        self.assertFalse(User.objects.filter(username='newuser').exists())

    @staticmethod
    def registration_data(**overrides):
        data = {
            'username': 'newuser',
            'email': 'newuser@test.com',
            'first_name': 'New',
            'last_name': 'Guy',
            'role': User.ROLE_MEMBER,
            'department': 'Eng',
            'job_title': 'Dev',
            'password': 'password123',
            'confirm_password': 'password123',
        }
        data.update(overrides)
        return data

    def test_registration_renders_required_email_and_password_errors(self):
        response = self.client.post(reverse('register'), {
            'username': 'validation_user',
            'email': '',
            'first_name': 'Validation',
            'last_name': 'User',
            'password': 'password123',
            'confirm_password': 'different123',
        })

        self.assertEqual(response.status_code, 200)
        self.assertIn('email', response.context['form'].errors)
        self.assertIn('confirm_password', response.context['form'].errors)
        self.assertContains(response, 'id="email-error"')
        self.assertContains(response, 'id="confirm_password-error"')

    def test_auth_pages_include_viewport_meta_and_registration_email_is_typed(self):
        login_response = self.client.get(reverse('login'))
        register_response = self.client.get(reverse('register'))

        self.assertContains(login_response, 'name="viewport"')
        self.assertContains(register_response, 'name="viewport"')
        self.assertEqual(
            register_response.context['form'].fields['email'].widget.input_type,
            'email',
        )
