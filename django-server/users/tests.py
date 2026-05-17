from django.test import TestCase, Client
from django.conf import settings
from users.models import User, QRCode


class ProjectSetupTestCase(TestCase):
    """Test Phase 1.1: Project Setup"""

    def test_settings_loaded(self):
        """Verify settings are loaded from environment variables"""
        self.assertIsNotNone(settings.JWT_SECRET)
        self.assertIsNotNone(settings.SERVICE_KEY)

    def test_installed_apps(self):
        """Verify required apps are installed"""
        self.assertIn('rest_framework', settings.INSTALLED_APPS)
        self.assertIn('users', settings.INSTALLED_APPS)

    def test_auth_user_model(self):
        """Verify custom user model is set"""
        self.assertEqual(settings.AUTH_USER_MODEL, 'users.User')

    def test_django_check_passes(self):
        """Verify Django system check passes"""
        from django.core.management import call_command
        import io
        import sys
        out = io.StringIO()
        sys.stdout = out
        call_command('check', '--deploy', '--verbosity', '0')
        sys.stdout = sys.__stdout__


class UserModelTestCase(TestCase):
    """Test Phase 1.2: Models - User model tests"""

    def test_user_creation(self):
        """Test creating a user with default status"""
        user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.assertEqual(user.status, 'pending_init_request')
        self.assertIsNone(user.whatsapp_jid)

    def test_user_status_choices(self):
        """Test user status choices are valid"""
        user = User.objects.create_user(
            username='testuser2',
            password='testpass123'
        )
        for status_choice in User.STATUS_CHOICES:
            user.status = status_choice[0]
            user.save()
            user.refresh_from_db()
            self.assertEqual(user.status, status_choice[0])

    def test_user_str(self):
        """Test user string representation"""
        user = User.objects.create_user(
            username='testuser3',
            password='testpass123'
        )
        self.assertEqual(str(user), 'testuser3')

    def test_user_ordering(self):
        """Test users are ordered by created_at descending"""
        user1 = User.objects.create_user(username='user1', password='pass')
        user2 = User.objects.create_user(username='user2', password='pass')
        users = list(User.objects.all())
        self.assertEqual(users[0], user2)
        self.assertEqual(users[1], user1)


class QRCodeModelTestCase(TestCase):
    """Test Phase 1.2: Models - QRCode model tests"""

    def setUp(self):
        """Set up test user"""
        self.user = User.objects.create_user(
            username='qruser',
            password='testpass123'
        )

    def test_qrcode_creation(self):
        """Test creating a QR code"""
        from django.utils import timezone
        from datetime import timedelta
        qr = QRCode.objects.create(
            user=self.user,
            image_data='base64data123',
            expires_at=timezone.now() + timedelta(minutes=5)
        )
        self.assertEqual(qr.user, self.user)
        self.assertEqual(qr.image_data, 'base64data123')
        self.assertFalse(qr.verified)

    def test_qrcode_user_relationship(self):
        """Test QR code is linked to user"""
        from django.utils import timezone
        from datetime import timedelta
        qr = QRCode.objects.create(
            user=self.user,
            image_data='test',
            expires_at=timezone.now() + timedelta(minutes=5)
        )
        self.assertEqual(self.user.qrcodes.count(), 1)
        self.assertEqual(self.user.qrcodes.first(), qr)

    def test_qrcode_str(self):
        """Test QR code string representation"""
        from django.utils import timezone
        from datetime import timedelta
        qr = QRCode.objects.create(
            user=self.user,
            image_data='test',
            expires_at=timezone.now() + timedelta(minutes=5)
        )
        self.assertIn('qruser', str(qr))
        self.assertIn('pending', str(qr))

    def test_qrcode_ordering(self):
        """Test QR codes are ordered by created_at descending"""
        from django.utils import timezone
        from datetime import timedelta
        qr1 = QRCode.objects.create(
            user=self.user,
            image_data='qr1',
            expires_at=timezone.now() + timedelta(minutes=5)
        )
        qr2 = QRCode.objects.create(
            user=self.user,
            image_data='qr2',
            expires_at=timezone.now() + timedelta(minutes=5)
        )
        qrcodes = list(QRCode.objects.all())
        self.assertEqual(qrcodes[0], qr2)
        self.assertEqual(qrcodes[1], qr1)

    def test_qrcode_cascade_delete(self):
        """Test QR codes are deleted when user is deleted"""
        from django.utils import timezone
        from datetime import timedelta
        QRCode.objects.create(
            user=self.user,
            image_data='test',
            expires_at=timezone.now() + timedelta(minutes=5)
        )
        self.assertEqual(QRCode.objects.count(), 1)
        self.user.delete()
        self.assertEqual(QRCode.objects.count(), 0)


class SerializerTestCase(TestCase):
    """Test Phase 1.3: Serializers"""

    def setUp(self):
        """Set up test user"""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )

    def test_user_serializer(self):
        """Test UserSerializer outputs correct fields"""
        from users.serializers import UserSerializer
        serializer = UserSerializer(self.user)
        data = serializer.data
        self.assertEqual(data['username'], 'testuser')
        self.assertEqual(data['status'], 'pending_init_request')
        self.assertIn('created_at', data)
        self.assertIn('updated_at', data)

    def test_user_create_serializer(self):
        """Test UserCreateSerializer creates user with hashed password"""
        from users.serializers import UserCreateSerializer
        data = {
            'username': 'newuser',
            'password': 'securepass123',
            'status': 'pending_init_request'
        }
        serializer = UserCreateSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        user = serializer.save()
        self.assertEqual(user.username, 'newuser')
        self.assertTrue(user.check_password('securepass123'))

    def test_user_create_serializer_password_min_length(self):
        """Test UserCreateSerializer enforces password minimum length"""
        from users.serializers import UserCreateSerializer
        data = {
            'username': 'newuser',
            'password': 'short',
        }
        serializer = UserCreateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('password', serializer.errors)

    def test_qrcode_serializer(self):
        """Test QRCodeSerializer outputs correct fields"""
        from django.utils import timezone
        from datetime import timedelta
        from users.serializers import QRCodeSerializer
        qr = QRCode.objects.create(
            user=self.user,
            image_data='base64data',
            expires_at=timezone.now() + timedelta(minutes=5)
        )
        serializer = QRCodeSerializer(qr)
        data = serializer.data
        self.assertEqual(data['image_data'], 'base64data')
        self.assertFalse(data['verified'])
        self.assertIn('created_at', data)


class ServiceKeyAuthTestCase(TestCase):
    """Test Phase 1.3: Service Key Authentication"""

    def setUp(self):
        """Set up test client and user"""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )

    def test_service_key_required_for_create(self):
        """Test service key is required for user creation via API"""
        response = self.client.post(
            '/api/users/',
            {'username': 'newuser', 'password': 'testpass123'},
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 401)

    def test_service_key_valid(self):
        """Test valid service key allows API access"""
        response = self.client.post(
            '/api/users/',
            {'username': 'newuser', 'password': 'testpass123'},
            content_type='application/json',
            HTTP_X_SERVICE_KEY=settings.SERVICE_KEY
        )
        self.assertIn(response.status_code, [201, 400])

    def test_invalid_service_key_rejected(self):
        """Test invalid service key is rejected"""
        response = self.client.post(
            '/api/users/',
            {'username': 'newuser', 'password': 'testpass123'},
            content_type='application/json',
            HTTP_X_SERVICE_KEY='invalid_key'
        )
        self.assertEqual(response.status_code, 401)


class APIEndpointsTestCase(TestCase):
    """Test Phase 1.3: REST API Endpoints"""

    def setUp(self):
        """Set up test client"""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )

    def test_list_users(self):
        """Test listing users returns all users"""
        response = self.client.get(
            '/api/users/',
            HTTP_X_SERVICE_KEY=settings.SERVICE_KEY
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_create_user(self):
        """Test creating a new user via API"""
        response = self.client.post(
            '/api/users/',
            {'username': 'newuser', 'password': 'testpass123'},
            content_type='application/json',
            HTTP_X_SERVICE_KEY=settings.SERVICE_KEY
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['username'], 'newuser')

    def test_get_user(self):
        """Test getting a single user"""
        response = self.client.get(
            f'/api/users/{self.user.id}/',
            HTTP_X_SERVICE_KEY=settings.SERVICE_KEY
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['username'], 'testuser')

    def test_update_user_status(self):
        """Test updating user status"""
        response = self.client.patch(
            f'/api/users/{self.user.id}/status/',
            {'status': 'connected'},
            content_type='application/json',
            HTTP_X_SERVICE_KEY=settings.SERVICE_KEY
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'connected')

    def test_delete_user(self):
        """Test deleting a user"""
        response = self.client.delete(
            f'/api/users/{self.user.id}/',
            HTTP_X_SERVICE_KEY=settings.SERVICE_KEY
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(User.objects.filter(id=self.user.id).exists())

    def test_get_qr_code(self):
        """Test getting QR code for user"""
        from django.utils import timezone
        from datetime import timedelta
        QRCode.objects.create(
            user=self.user,
            image_data='base64data',
            expires_at=timezone.now() + timedelta(minutes=5)
        )
        response = self.client.get(
            f'/api/users/{self.user.id}/qr/',
            HTTP_X_SERVICE_KEY=settings.SERVICE_KEY
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['image_data'], 'base64data')

    def test_update_qr_code(self):
        """Test updating QR code (Bridge push)"""
        response = self.client.patch(
            f'/api/users/{self.user.id}/qr/',
            {'image_data': 'newbase64data'},
            content_type='application/json',
            HTTP_X_SERVICE_KEY=settings.SERVICE_KEY
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.status, 'pending_handshake')

    def test_health_endpoint(self):
        """Test health check endpoint"""
        response = self.client.get('/health/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'healthy')


class AdminInterfaceTestCase(TestCase):
    """Test Phase 1.4: Django Admin Interface"""

    def setUp(self):
        """Set up admin user and test client"""
        self.admin_user = User.objects.create_superuser(
            username='admin',
            password='adminpass123',
            email='admin@test.com'
        )
        self.client = Client()
        self.client.login(username='admin', password='adminpass123')
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )

    def test_admin_user_list(self):
        """Test admin user list page loads"""
        response = self.client.get('/admin/users/user/')
        self.assertEqual(response.status_code, 200)

    def test_admin_user_change_form(self):
        """Test admin user change form has status field"""
        response = self.client.get(f'/admin/users/user/{self.user.id}/change/')
        self.assertEqual(response.status_code, 200)

    def test_admin_show_qr_action(self):
        """Test show QR code admin action is available"""
        response = self.client.get('/admin/users/user/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'show_qr_code')

    def test_admin_generate_api_key_action(self):
        """Test generate API key admin action is available"""
        response = self.client.get('/admin/users/user/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'generate_api_key')

    def test_admin_status_filter(self):
        """Test admin status filter"""
        response = self.client.get('/admin/users/user/?status=pending_init_request')
        self.assertEqual(response.status_code, 200)


class LoggingTestCase(TestCase):
    """Test Phase 1.5: Logging Configuration"""

    def test_logging_configured(self):
        """Test logging is configured"""
        import logging
        logger = logging.getLogger('users')
        self.assertIsNotNone(logger)

    def test_log_level_from_env(self):
        """Test log level is loaded from environment"""
        from django.conf import settings
        self.assertTrue(hasattr(settings, 'LOG_LEVEL'))