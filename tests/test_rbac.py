"""
Tests for role-based access control (RBAC).
"""
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework.decorators import api_view
from rest_framework.response import Response
from apps.core.models import Tenant, UserTenant
from apps.core.permissions import require_role, require_owner, require_accountant_or_owner, require_any_role
from apps.core.auth_utils import generate_access_token

User = get_user_model()


@pytest.fixture
def tenant_a(db):
    """Create test tenant A."""
    return Tenant.objects.create(name="Tenant A")


@pytest.fixture
def tenant_b(db):
    """Create test tenant B."""
    return Tenant.objects.create(name="Tenant B")


@pytest.fixture
def owner_user(db, tenant_a):
    """Create user with OWNER role."""
    user = User.objects.create_user(
        username="owner",
        email="owner@example.com",
        password="OwnerPass123!",
        first_name="Owner",
        last_name="User"
    )
    UserTenant.objects.create(
        user=user,
        tenant=tenant_a,
        role=UserTenant.Role.OWNER
    )
    return user


@pytest.fixture
def accountant_user(db, tenant_a):
    """Create user with ACCOUNTANT role."""
    user = User.objects.create_user(
        username="accountant",
        email="accountant@example.com",
        password="AccountantPass123!",
        first_name="Accountant",
        last_name="User"
    )
    UserTenant.objects.create(
        user=user,
        tenant=tenant_a,
        role=UserTenant.Role.ACCOUNTANT
    )
    return user


@pytest.fixture
def viewer_user(db, tenant_a):
    """Create user with VIEWER role."""
    user = User.objects.create_user(
        username="viewer",
        email="viewer@example.com",
        password="ViewerPass123!",
        first_name="Viewer",
        last_name="User"
    )
    UserTenant.objects.create(
        user=user,
        tenant=tenant_a,
        role=UserTenant.Role.VIEWER
    )
    return user


@pytest.fixture
def salesperson_user(db, tenant_a):
    """Create user with SALESPERSON role."""
    user = User.objects.create_user(
        username="sales",
        email="sales@example.com",
        password="SalesPass123!",
        first_name="Sales",
        last_name="User"
    )
    UserTenant.objects.create(
        user=user,
        tenant=tenant_a,
        role=UserTenant.Role.SALESPERSON
    )
    return user


@pytest.fixture
def api_client():
    return APIClient()


def create_test_view_with_role(*roles):
    """Helper to create test views with specific role requirements."""
    @api_view(["GET"])
    @require_role(*roles)
    def test_view(request):
        return Response({"message": "Access granted"})
    return test_view


@pytest.mark.django_db
class TestRequireRole:
    """Test the @require_role decorator."""
    
    def test_owner_can_access_owner_only_endpoint(self, api_client, owner_user, tenant_a):
        """OWNER can access OWNER-only endpoints."""
        from django.urls import path
        from django.conf import settings
        
        # Create mock authenticated request
        api_client.force_authenticate(user=owner_user)
        
        # Manually set tenant context (normally done by middleware)
        view = create_test_view_with_role("OWNER")
        from django.test import RequestFactory
        factory = RequestFactory()
        request = factory.get('/test/')
        request.user = owner_user
        request.tenant_id = str(tenant_a.id)
        
        response = view(request)
        assert response.status_code == 200
        assert response.data["message"] == "Access granted"
    
    def test_accountant_cannot_access_owner_only_endpoint(self, api_client, accountant_user, tenant_a):
        """ACCOUNTANT cannot access OWNER-only endpoints."""
        view = create_test_view_with_role("OWNER")
        from django.test import RequestFactory
        factory = RequestFactory()
        request = factory.get('/test/')
        request.user = accountant_user
        request.tenant_id = str(tenant_a.id)
        
        response = view(request)
        assert response.status_code == 403
        assert "Insufficient permissions" in response.data["error"]
    
    def test_viewer_cannot_access_owner_only_endpoint(self, api_client, viewer_user, tenant_a):
        """VIEWER cannot access OWNER-only endpoints."""
        view = create_test_view_with_role("OWNER")
        from django.test import RequestFactory
        factory = RequestFactory()
        request = factory.get('/test/')
        request.user = viewer_user
        request.tenant_id = str(tenant_a.id)
        
        response = view(request)
        assert response.status_code == 403
    
    def test_multiple_allowed_roles(self, api_client, accountant_user, tenant_a):
        """Endpoint allows multiple roles (OWNER, ACCOUNTANT)."""
        view = create_test_view_with_role("OWNER", "ACCOUNTANT")
        from django.test import RequestFactory
        factory = RequestFactory()
        request = factory.get('/test/')
        request.user = accountant_user
        request.tenant_id = str(tenant_a.id)
        
        response = view(request)
        assert response.status_code == 200
    
    def test_viewer_cannot_access_owner_accountant_endpoint(self, api_client, viewer_user, tenant_a):
        """VIEWER cannot access OWNER/ACCOUNTANT endpoints."""
        view = create_test_view_with_role("OWNER", "ACCOUNTANT")
        from django.test import RequestFactory
        factory = RequestFactory()
        request = factory.get('/test/')
        request.user = viewer_user
        request.tenant_id = str(tenant_a.id)
        
        response = view(request)
        assert response.status_code == 403
    
    def test_unauthenticated_user_denied(self, api_client, tenant_a):
        """Unauthenticated users are denied access."""
        view = create_test_view_with_role("OWNER")
        from django.test import RequestFactory
        from django.contrib.auth.models import AnonymousUser
        factory = RequestFactory()
        request = factory.get('/test/')
        
        # Use Django's AnonymousUser
        request.user = AnonymousUser()
        request.tenant_id = str(tenant_a.id)
        
        response = view(request)
        assert response.status_code == 401
    
    def test_missing_tenant_context_denied(self, api_client, owner_user):
        """Request without tenant context is denied."""
        view = create_test_view_with_role("OWNER")
        from django.test import RequestFactory
        factory = RequestFactory()
        request = factory.get('/test/')
        request.user = owner_user
        request.tenant_id = None  # No tenant context
        
        response = view(request)
        assert response.status_code == 400
        assert "Tenant context not found" in response.data["error"]
    
    def test_user_not_in_tenant_denied(self, api_client, owner_user, tenant_b):
        """User cannot access endpoints in tenants they don't belong to."""
        view = create_test_view_with_role("OWNER")
        from django.test import RequestFactory
        factory = RequestFactory()
        request = factory.get('/test/')
        request.user = owner_user
        request.tenant_id = str(tenant_b.id)  # Different tenant
        
        response = view(request)
        assert response.status_code == 403
        assert "does not have access to this tenant" in response.data["error"]


@pytest.mark.django_db
class TestRoleShortcuts:
    """Test shortcut decorators."""
    
    def test_require_owner_shortcut(self, api_client, owner_user, tenant_a):
        """@require_owner shortcut works correctly."""
        @api_view(["GET"])
        @require_owner
        def test_view(request):
            return Response({"message": "Owner access"})
        
        from django.test import RequestFactory
        factory = RequestFactory()
        request = factory.get('/test/')
        request.user = owner_user
        request.tenant_id = str(tenant_a.id)
        
        response = test_view(request)
        assert response.status_code == 200
    
    def test_require_accountant_or_owner_allows_both(self, api_client, accountant_user, tenant_a):
        """@require_accountant_or_owner allows ACCOUNTANT."""
        @api_view(["GET"])
        @require_accountant_or_owner
        def test_view(request):
            return Response({"message": "Accountant access"})
        
        from django.test import RequestFactory
        factory = RequestFactory()
        request = factory.get('/test/')
        request.user = accountant_user
        request.tenant_id = str(tenant_a.id)
        
        response = test_view(request)
        assert response.status_code == 200
    
    def test_require_any_role_allows_all(self, api_client, viewer_user, tenant_a):
        """@require_any_role allows all role types."""
        @api_view(["GET"])
        @require_any_role
        def test_view(request):
            return Response({"message": "Any role access"})
        
        from django.test import RequestFactory
        factory = RequestFactory()
        request = factory.get('/test/')
        request.user = viewer_user
        request.tenant_id = str(tenant_a.id)
        
        response = test_view(request)
        assert response.status_code == 200


@pytest.mark.django_db
class TestMultiTenantRBAC:
    """Test RBAC with multi-tenant scenarios."""
    
    def test_user_different_roles_in_different_tenants(self, api_client, tenant_a, tenant_b):
        """User can have different roles in different tenants."""
        user = User.objects.create_user(
            username="multitenant",
            email="multi@example.com",
            password="MultiPass123!"
        )
        
        # OWNER in tenant A
        UserTenant.objects.create(user=user, tenant=tenant_a, role=UserTenant.Role.OWNER)
        # VIEWER in tenant B
        UserTenant.objects.create(user=user, tenant=tenant_b, role=UserTenant.Role.VIEWER)
        
        view = create_test_view_with_role("OWNER")
        from django.test import RequestFactory
        factory = RequestFactory()
        
        # Should have OWNER access in tenant A
        request_a = factory.get('/test/')
        request_a.user = user
        request_a.tenant_id = str(tenant_a.id)
        response_a = view(request_a)
        assert response_a.status_code == 200
        
        # Should NOT have OWNER access in tenant B (only VIEWER)
        request_b = factory.get('/test/')
        request_b.user = user
        request_b.tenant_id = str(tenant_b.id)
        response_b = view(request_b)
        assert response_b.status_code == 403
    
    def test_inactive_user_tenant_denied(self, api_client, owner_user, tenant_a):
        """Inactive user-tenant relationships are denied."""
        user_tenant = UserTenant.objects.get(user=owner_user, tenant=tenant_a)
        user_tenant.is_active = False
        user_tenant.save()
        
        view = create_test_view_with_role("OWNER")
        from django.test import RequestFactory
        factory = RequestFactory()
        request = factory.get('/test/')
        request.user = owner_user
        request.tenant_id = str(tenant_a.id)
        
        response = view(request)
        assert response.status_code == 403


@pytest.mark.django_db
class TestSalespersonRole:
    """Test SALESPERSON-specific role access."""
    
    def test_salesperson_can_access_sales_endpoints(self, api_client, salesperson_user, tenant_a):
        """SALESPERSON can access SALESPERSON-allowed endpoints."""
        view = create_test_view_with_role("SALESPERSON", "OWNER")
        from django.test import RequestFactory
        factory = RequestFactory()
        request = factory.get('/test/')
        request.user = salesperson_user
        request.tenant_id = str(tenant_a.id)
        
        response = view(request)
        assert response.status_code == 200
    
    def test_salesperson_cannot_access_financial_endpoints(self, api_client, salesperson_user, tenant_a):
        """SALESPERSON cannot access OWNER/ACCOUNTANT financial endpoints."""
        view = create_test_view_with_role("OWNER", "ACCOUNTANT")
        from django.test import RequestFactory
        factory = RequestFactory()
        request = factory.get('/test/')
        request.user = salesperson_user
        request.tenant_id = str(tenant_a.id)
        
        response = view(request)
        assert response.status_code == 403
