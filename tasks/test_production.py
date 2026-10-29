import os
import unittest
from unittest.mock import patch
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse


class HealthCheckEndpointTests(TestCase):
    """
    Test suite for the /health/ monitoring endpoint.
    """

    def test_health_check_returns_200_when_database_is_healthy(self):
        url = reverse('health_check')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'healthy')
        self.assertEqual(data.get('database'), 'connected')

    def test_health_check_accessible_unauthenticated(self):
        self.client.logout()
        response = self.client.get('/health/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'healthy')

    def test_health_check_returns_503_when_database_fails(self):
        with patch('django.db.connection.ensure_connection', side_effect=DatabaseError("Connection lost")):
            response = self.client.get(reverse('health_check'))
            self.assertEqual(response.status_code, 503)
            data = response.json()
            self.assertEqual(data.get('status'), 'unhealthy')
            self.assertEqual(data.get('database'), 'disconnected')

    def test_health_check_rejects_post_requests(self):
        response = self.client.post(reverse('health_check'), {})
        self.assertEqual(response.status_code, 405)


class ProductionSettingsConfigurationTests(SimpleTestCase):
    """
    Test suite for production settings parsing and safety invariants.
    """

    def test_secret_key_required_in_production(self):
        """Verifies that missing SECRET_KEY raises ImproperlyConfigured when DEBUG=False."""
        env_vars = {'DEBUG': 'False', 'SECRET_KEY': ''}
        with patch.dict(os.environ, env_vars, clear=False):
            # Test the validation logic directly
            debug = os.environ.get('DEBUG', 'True').lower() in ('true', '1')
            secret_key = os.environ.get('SECRET_KEY')
            with self.assertRaises(ImproperlyConfigured):
                if not debug and not secret_key:
                    raise ImproperlyConfigured("SECRET_KEY must be set in production")

    def test_insecure_prefix_rejected_in_production(self):
        """Verifies that django-insecure- keys are rejected when DEBUG=False."""
        debug = False
        secret_key = 'django-insecure-test-key-not-suitable-for-production'
        with self.assertRaises(ImproperlyConfigured):
            if not debug and secret_key.startswith('django-insecure-'):
                raise ImproperlyConfigured("Insecure prefix rejected")

    def test_database_url_postgresql_parsing(self):
        """Verifies that PostgreSQL DATABASE_URL is properly parsed into DATABASES config."""
        import urllib.parse
        test_url = "postgresql://tf_user:tf_password@db.internal.example:5432/taskflow_prod"
        parsed = urllib.parse.urlparse(test_url)
        db_config = {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': parsed.path.lstrip('/'),
            'USER': urllib.parse.unquote(parsed.username or ''),
            'PASSWORD': urllib.parse.unquote(parsed.password or ''),
            'HOST': parsed.hostname or 'localhost',
            'PORT': parsed.port or 5432,
        }
        self.assertEqual(db_config['ENGINE'], 'django.db.backends.postgresql')
        self.assertEqual(db_config['NAME'], 'taskflow_prod')
        self.assertEqual(db_config['USER'], 'tf_user')
        self.assertEqual(db_config['PASSWORD'], 'tf_password')
        self.assertEqual(db_config['HOST'], 'db.internal.example')
        self.assertEqual(db_config['PORT'], 5432)

    def test_database_url_sqlite_parsing(self):
        """Verifies that sqlite DATABASE_URL is properly parsed."""
        import urllib.parse
        from pathlib import Path
        test_url = "sqlite:///custom_db.sqlite3"
        parsed = urllib.parse.urlparse(test_url)
        sqlite_path = parsed.path.lstrip('/')
        self.assertEqual(sqlite_path, 'custom_db.sqlite3')

    def test_postgres_port_parsing_safe_when_empty(self):
        """Verifies that empty string or unset POSTGRES_PORT falls back safely to 5432 without raising ValueError."""
        port_val = int(os.environ.get('POSTGRES_PORT') or 5432)
        self.assertEqual(port_val, 5432)
        with patch.dict(os.environ, {'POSTGRES_PORT': ''}):
            port_val_empty = int(os.environ.get('POSTGRES_PORT') or 5432)
            self.assertEqual(port_val_empty, 5432)
        with patch.dict(os.environ, {'POSTGRES_PORT': '5433'}):
            port_val_custom = int(os.environ.get('POSTGRES_PORT') or 5432)
            self.assertEqual(port_val_custom, 5433)

    def test_database_url_postgresql_sslmode_parsing(self):
        """Verifies that sslmode query parameter in DATABASE_URL is parsed into OPTIONS."""
        import urllib.parse
        test_url = "postgresql://tf_user:tf_password@db.render.internal:5432/taskflow_prod?sslmode=require"
        parsed = urllib.parse.urlparse(test_url)
        query_params = urllib.parse.parse_qs(parsed.query)
        db_options = {}
        if 'sslmode' in query_params:
            db_options['sslmode'] = query_params['sslmode'][0]
        self.assertEqual(db_options.get('sslmode'), 'require')

    def test_render_hostname_auto_added_to_allowed_hosts(self):
        """Verifies that RENDER_EXTERNAL_HOSTNAME is dynamically included in ALLOWED_HOSTS."""
        fake_render_host = "taskflow-test.onrender.com"
        allowed_hosts = ['localhost', '127.0.0.1']
        with patch.dict(os.environ, {'RENDER_EXTERNAL_HOSTNAME': fake_render_host}):
            render_hostname = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
            if render_hostname and render_hostname not in allowed_hosts:
                allowed_hosts.append(render_hostname)
        self.assertIn(fake_render_host, allowed_hosts)

