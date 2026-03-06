"""
Email verification flow tests.
"""
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.core.auth_utils import generate_email_verification_token

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def unverified_user(db):
    user = User.objects.create_user(
        username="unverified",
        email="unverified@example.com",
        password="TestPass123!",
    )
    assert not user.is_email_verified
    return user


@pytest.mark.django_db
class TestEmailVerification:

    def test_valid_token_verifies_email(self, api_client, unverified_user):
        token = generate_email_verification_token(unverified_user.id)
        response = api_client.post("/api/auth/verify-email/", {"token": token}, format="json")

        assert response.status_code == 200
        unverified_user.refresh_from_db()
        assert unverified_user.is_email_verified

    def test_already_verified_returns_200(self, api_client, unverified_user):
        unverified_user.is_email_verified = True
        unverified_user.save()

        token = generate_email_verification_token(unverified_user.id)
        response = api_client.post("/api/auth/verify-email/", {"token": token}, format="json")

        assert response.status_code == 200
        assert "already verified" in response.data["message"].lower()

    def test_invalid_token_returns_400(self, api_client):
        response = api_client.post(
            "/api/auth/verify-email/", {"token": "not-a-real-token"}, format="json"
        )
        assert response.status_code == 400

    def test_missing_token_returns_400(self, api_client):
        response = api_client.post("/api/auth/verify-email/", {}, format="json")
        assert response.status_code == 400

    def test_register_sends_verification_email(self, api_client):
        from django.core import mail

        api_client.post(
            "/api/auth/register/",
            {
                "username": "emailtest",
                "email": "emailtest@example.com",
                "password": "SecurePass123!",
                "tenant_name": "Email Test Co",
            },
            format="json",
        )

        assert len(mail.outbox) == 1
        assert "emailtest@example.com" in mail.outbox[0].to
        assert "verify" in mail.outbox[0].subject.lower()
