import secrets
import logging
from rest_framework import authentication, exceptions

logger = logging.getLogger(__name__)


class ServiceKeyAuthentication(authentication.BaseAuthentication):
    """Service Key authentication for internal service-to-service calls"""

    def authenticate(self, request):
        from django.conf import settings
        expected_key = getattr(settings, 'SERVICE_KEY', '')

        service_key = request.headers.get('X-Service-Key')

        if not expected_key:
            logger.warning("SERVICE_KEY not configured")
            if service_key:
                raise exceptions.AuthenticationFailed('Service key not configured but key provided')
            return None

        if not service_key:
            logger.warning("Service key required but not provided")
            raise exceptions.AuthenticationFailed('Service key required')

        if not secrets.compare_digest(service_key, expected_key):
            logger.warning("Invalid service key attempted")
            raise exceptions.AuthenticationFailed('Invalid service key')

        logger.debug("Service key authentication successful")
        return (None, 'service_key')

    def authenticate_header(self, request):
        return 'X-Service-Key'