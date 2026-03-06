"""
Authentication system tests.
"""
import pytest
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.core.models import Tenant, UserTenant, RefreshToken
from apps.core.auth_utils import generate_refresh_token, verify_access_token

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def test_user(db):
    """Create a test user with a tenant."""
    user = User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="TestPass123!",
        first_name="Test",
        last_name="User"
    )
    tenant = Tenant.objects.create(name="Test Business")
    UserTenant.objects.create(
        user=user,
        tenant=tenant,
        role=UserTenant.Role.OWNER
    )
    return user


@pytest.mark.django_db
class TestUserRegistration:
    """Test user registration endpoint."""
    
    def test_successful_registration(self, api_client):
        """User can register with valid data."""
        data = {
            "username": "newuser",
            "email": "newuser@example.com",
            "password": "SecurePass123!",
            "first_name": "New",
            "last_name": "User",
            "tenant_name": "My New Business"
        }
        
        response = api_client.post("/api/auth/register/", data, format="json")
        
        assert response.status_code == 201
        assert "access_token" in response.data
        assert "refresh_token" in response.data
        assert response.data["user"]["username"] == "newuser"
        assert response.data["user"]["email"] == "newuser@example.com"
        
        # Verify user was created
        user = User.objects.get(username="newuser")
        assert user.email == "newuser@example.com"
        assert user.check_password("SecurePass123!")
        
        # Verify tenant was created
        assert user.user_tenants.count() == 1
        user_tenant = user.user_tenants.first()
        assert user_tenant.tenant.name == "My New Business"
        assert user_tenant.role == UserTenant.Role.OWNER
        
        # Verify refresh token was stored
        assert RefreshToken.objects.filter(user=user).exists()
    
    def test_duplicate_email(self, api_client, test_user):
        """Cannot register with duplicate email."""
        data = {
            "username": "anotheruser",
            "email": "test@example.com",  # Already used
            "password": "SecurePass123!",
            "tenant_name": "Another Business"
        }
        
        response = api_client.post("/api/auth/register/", data, format="json")
        
        assert response.status_code == 400
        assert "email" in response.data
    
    def test_duplicate_username(self, api_client, test_user):
        """Cannot register with duplicate username."""
        data = {
            "username": "testuser",  # Already used
            "email": "another@example.com",
            "password": "SecurePass123!",
            "tenant_name": "Another Business"
        }
        
        response = api_client.post("/api/auth/register/", data, format="json")
        
        assert response.status_code == 400
        assert "username" in response.data
    
    def test_weak_password(self, api_client):
        """Cannot register with weak password."""
        data = {
            "username": "newuser",
            "email": "newuser@example.com",
            "password": "123",  # Too short
            "tenant_name": "My Business"
        }
        
        response = api_client.post("/api/auth/register/", data, format="json")
        
        assert response.status_code == 400
        assert "password" in response.data


@pytest.mark.django_db
class TestLogin:
    """Test login endpoint."""
    
    def test_successful_login(self, api_client, test_user):
        """User can login with valid credentials."""
        data = {
            "username": "testuser",
            "password": "TestPass123!"
        }
        
        response = api_client.post("/api/auth/login/", data, format="json")
        
        assert response.status_code == 200
        assert "access_token" in response.data
        assert "refresh_token" in response.data
        assert response.data["user"]["username"] == "testuser"
        
        # Verify refresh token was stored
        assert RefreshToken.objects.filter(user=test_user).exists()
    
    def test_invalid_credentials(self, api_client, test_user):
        """Cannot login with invalid password."""
        data = {
            "username": "testuser",
            "password": "WrongPassword123!"
        }
        
        response = api_client.post("/api/auth/login/", data, format="json")
        
        assert response.status_code == 400
    
    def test_nonexistent_user(self, api_client):
        """Cannot login with nonexistent username."""
        data = {
            "username": "doesnotexist",
            "password": "SomePassword123!"
        }
        
        response = api_client.post("/api/auth/login/", data, format="json")
        
        assert response.status_code == 400
    
    def test_inactive_user(self, api_client, test_user):
        """Cannot login if user account is inactive."""
        test_user.is_active = False
        test_user.save()
        
        data = {
            "username": "testuser",
            "password": "TestPass123!"
        }
        
        response = api_client.post("/api/auth/login/", data, format="json")
        
        assert response.status_code == 400


@pytest.mark.django_db
class TestTokenRefresh:
    """Test token refresh endpoint."""
    
    def test_successful_refresh(self, api_client, test_user):
        """Can refresh access token with valid refresh token."""
        # Generate refresh token
        refresh_token_str = generate_refresh_token(test_user.id)
        RefreshToken.objects.create(
            user=test_user,
            token=refresh_token_str,
            expires_at=timezone.now() + timezone.timedelta(days=7)
        )
        
        data = {
            "refresh_token": refresh_token_str
        }
        
        response = api_client.post("/api/auth/refresh/", data, format="json")
        
        assert response.status_code == 200
        assert "access_token" in response.data
        
        # Verify new access token is valid
        payload = verify_access_token(response.data["access_token"])
        assert payload is not None
        assert payload["user_id"] == str(test_user.id)
    
    def test_invalid_refresh_token(self, api_client):
        """Cannot refresh with invalid token."""
        data = {
            "refresh_token": "invalid.token.here"
        }
        
        response = api_client.post("/api/auth/refresh/", data, format="json")
        
        assert response.status_code == 400
    
    def test_revoked_refresh_token(self, api_client, test_user):
        """Cannot refresh with revoked token."""
        refresh_token_str = generate_refresh_token(test_user.id)
        refresh_token_obj = RefreshToken.objects.create(
            user=test_user,
            token=refresh_token_str,
            expires_at=timezone.now() + timezone.timedelta(days=7),
            revoked=True,
            revoked_at=timezone.now()
        )
        
        data = {
            "refresh_token": refresh_token_str
        }
        
        response = api_client.post("/api/auth/refresh/", data, format="json")
        
        assert response.status_code == 400
        assert "revoked" in response.data["error"].lower()
    
    def test_expired_refresh_token(self, api_client, test_user):
        """Cannot refresh with expired token."""
        refresh_token_str = generate_refresh_token(test_user.id)
        RefreshToken.objects.create(
            user=test_user,
            token=refresh_token_str,
            expires_at=timezone.now() - timezone.timedelta(days=1)  # Expired
        )
        
        data = {
            "refresh_token": refresh_token_str
        }
        
        response = api_client.post("/api/auth/refresh/", data, format="json")
        
        assert response.status_code == 400


@pytest.mark.django_db
class TestLogout:
    """Test logout endpoint."""
    
    def test_successful_logout(self, api_client, test_user):
        """User can logout and revoke refresh token."""
        # Login first to get tokens
        login_data = {
            "username": "testuser",
            "password": "TestPass123!"
        }
        login_response = api_client.post("/api/auth/login/", login_data, format="json")
        access_token = login_response.data["access_token"]
        refresh_token_str = login_response.data["refresh_token"]
        
        # Logout
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        logout_data = {
            "refresh_token": refresh_token_str
        }
        
        response = api_client.post("/api/auth/logout/", logout_data, format="json")
        
        assert response.status_code == 204
        
        # Verify token was revoked
        refresh_token_obj = RefreshToken.objects.get(token=refresh_token_str)
        assert refresh_token_obj.revoked is True
        assert refresh_token_obj.revoked_at is not None
    
    def test_logout_without_auth(self, api_client):
        """Cannot logout without authentication."""
        data = {
            "refresh_token": "some.refresh.token"
        }
        
        response = api_client.post("/api/auth/logout/", data, format="json")
        
        assert response.status_code == 401


@pytest.mark.django_db
class TestJWTAuthentication:
    """Test JWT authentication middleware."""
    
    def test_access_protected_endpoint_with_valid_token(self, api_client, test_user):
        """Can access protected endpoint with valid JWT."""
        # Login to get token
        login_data = {
            "username": "testuser",
            "password": "TestPass123!"
        }
        login_response = api_client.post("/api/auth/login/", login_data, format="json")
        access_token = login_response.data["access_token"]
        
        # Access logout endpoint (requires authentication)
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        response = api_client.post("/api/auth/logout/", {"refresh_token": "dummy"}, format="json")
        
        # Should not get 401 (even if it fails validation for other reasons)
        assert response.status_code != 401
    
    def test_access_protected_endpoint_without_token(self, api_client):
        """Cannot access protected endpoint without JWT."""
        # Try to access logout without token
        response = api_client.post("/api/auth/logout/", {"refresh_token": "dummy"}, format="json")
        
        assert response.status_code == 401
    
    def test_access_protected_endpoint_with_invalid_token(self, api_client):
        """Cannot access protected endpoint with invalid JWT."""
        api_client.credentials(HTTP_AUTHORIZATION="Bearer invalid.token.here")
        response = api_client.post("/api/auth/logout/", {"refresh_token": "dummy"}, format="json")
        
        assert response.status_code == 401


@pytest.mark.django_db
class TestTenantIsolationInAuth:
    """Test tenant isolation in authentication."""
    
    def test_access_token_includes_tenant_id(self, api_client, test_user):
        """Access token includes tenant_id from user's tenant."""
        login_data = {
            "username": "testuser",
            "password": "TestPass123!"
        }
        
        response = api_client.post("/api/auth/login/", login_data, format="json")
        
        assert response.status_code == 200
        access_token = response.data["access_token"]
        
        # Decode token and verify tenant_id
        payload = verify_access_token(access_token)
        assert payload is not None
        assert "tenant_id" in payload
        
        user_tenant = test_user.user_tenants.first()
        assert payload["tenant_id"] == str(user_tenant.tenant.id)
    
    def test_user_with_multiple_tenants(self, api_client, test_user):
        """User with multiple tenants gets first active tenant in token."""
        # Create second tenant
        tenant_2 = Tenant.objects.create(name="Second Business")
        UserTenant.objects.create(
            user=test_user,
            tenant=tenant_2,
            role=UserTenant.Role.ACCOUNTANT
        )
        
        login_data = {
            "username": "testuser",
            "password": "TestPass123!"
        }
        
        response = api_client.post("/api/auth/login/", login_data, format="json")
        
        assert response.status_code == 200
        access_token = response.data["access_token"]
        
        # Token should include one of the tenants
        payload = verify_access_token(access_token)
        assert payload is not None
        assert "tenant_id" in payload
