"""
Password reset flow tests.
"""
import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from rest_framework.test import APIClient
from apps.core.auth_utils import generate_password_reset_token
from apps.core.models import RefreshToken
from django.utils import timezone

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def active_user(db):
    return User.objects.create_user(
        username="resetuser",
        email="reset@example.com",
        password="OldPass123!",
    )


@pytest.mark.django_db
class TestForgotPassword:

    def test_valid_email_sends_reset_link(self, api_client, active_user):
        response = api_client.post(
            "/api/auth/forgot-password/", {"email": "reset@example.com"}, format="json"
        )
        assert response.status_code == 200
        assert len(mail.outbox) == 1
        assert "reset@example.com" in mail.outbox[0].to

    def test_unknown_email_returns_200_no_email(self, api_client, db):
        """Response is identical to prevent email enumeration."""
        response = api_client.post(
            "/api/auth/forgot-password/", {"email": "nobody@example.com"}, format="json"
        )
        assert response.status_code == 200
        assert len(mail.outbox) == 0

    def test_missing_email_returns_400(self, api_client):
        response = api_client.post("/api/auth/forgot-password/", {}, format="json")
        assert response.status_code == 400


@pytest.mark.django_db
class TestResetPassword:

    def test_valid_token_resets_password(self, api_client, active_user):
        token = generate_password_reset_token(active_user)
        response = api_client.post(
            "/api/auth/reset-password/",
            {"token": token, "new_password": "NewSecurePass123!"},
            format="json",
        )
        assert response.status_code == 200
        active_user.refresh_from_db()
        assert active_user.check_password("NewSecurePass123!")

    def test_reset_revokes_all_refresh_tokens(self, api_client, active_user):
        RefreshToken.objects.create(
            user=active_user,
            token="sometoken123",
            expires_at=timezone.now() + timezone.timedelta(days=7),
        )
        token = generate_password_reset_token(active_user)
        api_client.post(
            "/api/auth/reset-password/",
            {"token": token, "new_password": "NewSecurePass123!"},
            format="json",
        )
        assert RefreshToken.objects.filter(user=active_user, revoked=False).count() == 0

    def test_invalid_token_returns_400(self, api_client):
        response = api_client.post(
            "/api/auth/reset-password/",
            {"token": "invalid-token", "new_password": "NewSecurePass123!"},
            format="json",
        )
        assert response.status_code == 400

    def test_missing_fields_returns_400(self, api_client):
        response = api_client.post("/api/auth/reset-password/", {}, format="json")
        assert response.status_code == 400
