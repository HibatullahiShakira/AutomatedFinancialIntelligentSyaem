"""
Role-based access control decorators for protecting API endpoints.
"""
from functools import wraps
from typing import Callable, Any
from rest_framework.response import Response
from rest_framework import status
from apps.core.models import UserTenant


def require_role(*allowed_roles: str) -> Callable:
    """
    Decorator to require specific role(s) for accessing an endpoint.

    Usage:
        @require_role("OWNER")
        def delete_business(request):
            ...

        @require_role("OWNER", "ACCOUNTANT")
        def view_finances(request):
            ...

    Args:
        *allowed_roles: One or more role names (OWNER, ACCOUNTANT, VIEWER, SALESPERSON)

    Returns:
        Decorated function that checks user's role in current tenant
    """
    def decorator(view_func: Callable) -> Callable:
        @wraps(view_func)
        def wrapper(request: Any, *args: Any, **kwargs: Any) -> Any:
            # Check if user is authenticated
            if not hasattr(request, 'user') or not request.user.is_authenticated:
                return Response(
                    {"error": "Authentication required"},
                    status=status.HTTP_401_UNAUTHORIZED
                )

            # Check if tenant context is set
            if not hasattr(request, 'tenant_id') or request.tenant_id is None:
                return Response(
                    {"error": "Tenant context not found"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Get user's role in this tenant
            try:
                user_tenant = UserTenant.objects.get(
                    user=request.user,
                    tenant_id=request.tenant_id,
                    is_active=True
                )

                if user_tenant.role not in allowed_roles:
                    return Response(
                        {
                            "error": f"Insufficient permissions. Required role(s): {', '.join(allowed_roles)}",
                            "user_role": user_tenant.role
                        },
                        status=status.HTTP_403_FORBIDDEN
                    )

                # Role check passed, execute the view
                return view_func(request, *args, **kwargs)

            except UserTenant.DoesNotExist:
                return Response(
                    {"error": "User does not have access to this tenant"},
                    status=status.HTTP_403_FORBIDDEN
                )

        return wrapper
    return decorator


def require_owner(view_func: Callable) -> Callable:
    """Shortcut decorator for OWNER-only endpoints."""
    return require_role("OWNER")(view_func)


def require_accountant_or_owner(view_func: Callable) -> Callable:
    """Shortcut decorator for endpoints accessible by OWNER or ACCOUNTANT."""
    return require_role("OWNER", "ACCOUNTANT")(view_func)


def require_any_role(view_func: Callable) -> Callable:
    """Decorator that allows any authenticated user with tenant access."""
    return require_role("OWNER", "ACCOUNTANT", "VIEWER", "SALESPERSON")(view_func)
