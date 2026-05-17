import jwt
import os
import logging
import requests
from functools import wraps
from typing import Optional

logger = logging.getLogger(__name__)

JWT_SECRET = os.environ.get("JWT_SECRET", "your-256-bit-secret-key-here-change-in-production")
SERVICE_KEY = os.environ.get("SERVICE_KEY", "service-key-here")
DJANGO_API_URL = os.environ.get("DJANGO_API_URL", "http://localhost:18080")


def validate_jwt(token: str) -> Optional[str]:
    """Validate JWT and return user_id."""
    if not token:
        return None
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_signature": True}
        )
        user_id = payload.get("user_id") or payload.get("sub")
        if user_id:
            logger.info(f"JWT validated for user_id: {user_id}")
            return user_id
        return None
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWT validation failed: {e}")
        return None


def validate_service_key(request) -> bool:
    """Validate X-Service-Key header."""
    key = request.headers.get('X-Service-Key')
    if not key:
        logger.warning("Missing service key header")
        return False
    import secrets
    if not secrets.compare_digest(key, SERVICE_KEY):
        logger.warning("Invalid service key")
        return False
    return True


def check_user_exists_in_django(user_id: str) -> bool:
    """Check if user still exists in Django. Returns True if user exists."""
    if not DJANGO_API_URL:
        logger.warning("DJANGO_API_URL not configured, skipping user existence check")
        return True
    try:
        headers = {"X-Service-Key": SERVICE_KEY} if SERVICE_KEY else {}
        response = requests.get(
            f"{DJANGO_API_URL}/api/users/{user_id}/",
            headers=headers,
            timeout=5
        )
        if response.status_code == 200:
            return True
        elif response.status_code == 404:
            logger.warning(f"User {user_id} not found in Django - access denied")
            return False
        else:
            logger.error(f"Unexpected response from Django: {response.status_code}")
            return False
    except requests.RequestException as e:
        logger.error(f"Failed to check user existence in Django: {e}")
        return False


def extract_user_id_from_env() -> Optional[str]:
    """Extract user_id from environment (for internal service calls)."""
    return os.environ.get("USER_ID")


def validate_user_for_request(jwt_user_id: str, requested_user_id: str) -> str:
    """Validate that the request targets the correct user."""
    if jwt_user_id != requested_user_id:
        logger.error(f"User ID mismatch: JWT={jwt_user_id}, Requested={requested_user_id}")
        raise PermissionError("User ID mismatch")
    return jwt_user_id


def validate_no_user_id_in_arguments(arguments: dict) -> None:
    """Ensure tool arguments don't contain user_id that could conflict with JWT."""
    if "user_id" in arguments:
        logger.error(f"Attempt to override user_id via tool arguments")
        raise PermissionError("user_id cannot be passed as tool argument")