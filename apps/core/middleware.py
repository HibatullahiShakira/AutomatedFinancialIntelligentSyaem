import uuid
import time
import logging
from django.utils.deprecation import MiddlewareMixin
from django.http import JsonResponse
from typing import Any
from apps.core.auth_utils import verify_access_token, is_access_token_revoked
from apps.core.models import User

logger = logging.getLogger("amss.requests")


class CorrelationIdMiddleware(MiddlewareMixin):
    """Assign unique ID to every request for distributed tracing. See CODE_LEARNING_GUIDE.md"""
    def process_request(self, request: Any) -> None:
        request.correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        request._start_time = time.monotonic()


class RequestLoggingMiddleware(MiddlewareMixin):
    """Log method, path, status code, and duration for every request."""

    def process_response(self, request: Any, response: Any) -> Any:
        start = getattr(request, "_start_time", None)
        duration_ms = round((time.monotonic() - start) * 1000) if start is not None else -1
        correlation_id = getattr(request, "correlation_id", "-")
        logger.info(
            "%s %s %s %dms cid=%s",
            request.method,
            request.path,
            response.status_code,
            duration_ms,
            correlation_id,
        )
        return response


class JWTAuthenticationMiddleware(MiddlewareMixin):
    """Extract and validate JWT from Authorization header."""

    EXEMPT_PATHS = ["/api/auth/register/", "/api/auth/login/", "/api/auth/refresh/", "/admin/"]

    def process_request(self, request: Any) -> Any:
        # Skip authentication for exempt paths
        if any(request.path.startswith(path) for path in self.EXEMPT_PATHS):
            return None

        # Extract token from Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return JsonResponse(
                {"error": "Authorization header required"},
                status=401
            )

        # Parse Bearer token
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return JsonResponse(
                {"error": "Invalid Authorization header format. Use: Bearer <token>"},
                status=401
            )

        token = parts[1]

        # Verify token
        payload = verify_access_token(token)
        if not payload:
            return JsonResponse(
                {"error": "Invalid or expired token"},
                status=401
            )

        # Check if access token has been revoked (e.g. after logout)
        if is_access_token_revoked(payload):
            return JsonResponse(
                {"error": "Token has been revoked"},
                status=401
            )

        # Get user from payload
        try:
            user = User.objects.get(id=payload["user_id"])
        except User.DoesNotExist:
            return JsonResponse(
                {"error": "User not found"},
                status=401
            )

        if not user.is_active:
            return JsonResponse(
                {"error": "User account is inactive"},
                status=401
            )

        # Set request attributes
        request.user = user
        request.tenant_id = payload.get("tenant_id")
        request.jwt_payload = payload

        return None


class TenantContextMiddleware(MiddlewareMixin):
    """Inject tenant context into every request. See CODE_LEARNING_GUIDE.md"""
    def process_request(self, request: Any) -> None:
        # tenant_id is now set by JWTAuthenticationMiddleware
        if not hasattr(request, "tenant_id"):
            request.tenant_id = None
