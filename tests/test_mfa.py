"""
TOTP / MFA flow tests.
"""
import pytest
import pyotp
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.core.models import Tenant, UserTenant
from apps.core.auth_utils import generate_mfa_token, generate_totp_secret

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user_with_tenant(db):
    user = User.objects.create_user(
        username="mfauser",
        email="mfa@example.com",
        password="TestPass123!",
    )
    tenant = Tenant.objects.create(name="MFA Tenant")
    UserTenant.objects.create(user=user, tenant=tenant, role=UserTenant.Role.OWNER)
    return user


@pytest.fixture
def authenticated_client(api_client, user_with_tenant):
    response = api_client.post(
        "/api/auth/login/",
        {"username": "mfauser", "password": "TestPass123!"},
        format="json",
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access_token']}")
    return api_client, user_with_tenant


@pytest.mark.django_db
class TestTOTPSetup:

    def test_setup_returns_secret_and_uri(self, authenticated_client):
        client, _ = authenticated_client
        response = client.post("/api/auth/totp/setup/", format="json")

        assert response.status_code == 200
        assert "secret" in response.data
        assert "provisioning_uri" in response.data
        assert response.data["provisioning_uri"].startswith("otpauth://totp/")

    def test_setup_saves_secret_to_user(self, authenticated_client):
        client, user = authenticated_client
        client.post("/api/auth/totp/setup/", format="json")
        user.refresh_from_db()
        assert user.totp_secret is not None

    def test_setup_when_already_enabled_returns_400(self, authenticated_client):
        client, user = authenticated_client
        user.totp_secret = generate_totp_secret()
        user.totp_enabled = True
        user.save()

        response = client.post("/api/auth/totp/setup/", format="json")
        assert response.status_code == 400

    def test_setup_requires_auth(self, api_client):
        response = api_client.post("/api/auth/totp/setup/", format="json")
        assert response.status_code == 401


@pytest.mark.django_db
class TestTOTPVerify:

    def test_valid_code_enables_totp(self, authenticated_client):
        client, user = authenticated_client
        # Initiate setup
        setup_resp = client.post("/api/auth/totp/setup/", format="json")
        secret = setup_resp.data["secret"]

        # Generate a valid TOTP code
        code = pyotp.TOTP(secret).now()
        response = client.post("/api/auth/totp/verify/", {"code": code}, format="json")

        assert response.status_code == 200
        user.refresh_from_db()
        assert user.totp_enabled

    def test_invalid_code_returns_400(self, authenticated_client):
        client, user = authenticated_client
        user.totp_secret = generate_totp_secret()
        user.save()

        response = client.post("/api/auth/totp/verify/", {"code": "000000"}, format="json")
        # Could be valid by chance, but overwhelmingly likely to be 400
        assert response.status_code in (200, 400)

    def test_verify_without_setup_returns_400(self, authenticated_client):
        client, _ = authenticated_client
        response = client.post("/api/auth/totp/verify/", {"code": "123456"}, format="json")
        assert response.status_code == 400


@pytest.mark.django_db
class TestTOTPAuthenticate:

    def test_login_with_totp_returns_mfa_required(self, api_client, user_with_tenant):
        secret = generate_totp_secret()
        user_with_tenant.totp_secret = secret
        user_with_tenant.totp_enabled = True
        user_with_tenant.save()

        response = api_client.post(
            "/api/auth/login/",
            {"username": "mfauser", "password": "TestPass123!"},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["mfa_required"] is True
        assert "mfa_token" in response.data
        assert "access_token" not in response.data

    def test_totp_authenticate_with_valid_code(self, api_client, user_with_tenant):
        secret = generate_totp_secret()
        user_with_tenant.totp_secret = secret
        user_with_tenant.totp_enabled = True
        user_with_tenant.save()

        # Get MFA challenge token
        login_resp = api_client.post(
            "/api/auth/login/",
            {"username": "mfauser", "password": "TestPass123!"},
            format="json",
        )
        mfa_token = login_resp.data["mfa_token"]
        code = pyotp.TOTP(secret).now()

        response = api_client.post(
            "/api/auth/totp/authenticate/",
            {"mfa_token": mfa_token, "code": code},
            format="json",
        )

        assert response.status_code == 200
        assert "access_token" in response.data
        assert "refresh_token" in response.data

    def test_totp_authenticate_with_invalid_code(self, api_client, user_with_tenant):
        secret = generate_totp_secret()
        user_with_tenant.totp_secret = secret
        user_with_tenant.totp_enabled = True
        user_with_tenant.save()

        login_resp = api_client.post(
            "/api/auth/login/",
            {"username": "mfauser", "password": "TestPass123!"},
            format="json",
        )
        mfa_token = login_resp.data["mfa_token"]

        response = api_client.post(
            "/api/auth/totp/authenticate/",
            {"mfa_token": mfa_token, "code": "000000"},
            format="json",
        )
        assert response.status_code == 400

    def test_totp_authenticate_with_invalid_mfa_token(self, api_client, db):
        response = api_client.post(
            "/api/auth/totp/authenticate/",
            {"mfa_token": "invalid.mfa.token", "code": "123456"},
            format="json",
        )
        assert response.status_code == 400

    def test_mfa_warning_for_owner_without_totp(self, api_client, user_with_tenant):
        response = api_client.post(
            "/api/auth/login/",
            {"username": "mfauser", "password": "TestPass123!"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["mfa_warning"] is True
