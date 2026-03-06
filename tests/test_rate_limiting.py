"""
Rate limiting tests for login and register endpoints.
"""
import pytest
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from apps.core.models import Tenant, UserTenant

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def existing_user(db):
    user = User.objects.create_user(
        username="ratelimituser",
        email="ratelimit@example.com",
        password="TestPass123!",
    )
    tenant = Tenant.objects.create(name="Rate Limit Tenant")
    UserTenant.objects.create(user=user, tenant=tenant, role=UserTenant.Role.OWNER)
    return user


@pytest.mark.django_db
class TestLoginRateLimit:

    def test_login_throttled_after_limit(self, api_client, existing_user, settings):
        """After 10 failed login attempts, the endpoint returns 429."""
        settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["login"] = "5/minute"

        data = {"username": "ratelimituser", "password": "WrongPassword!"}
        responses = [
            api_client.post("/api/auth/login/", data, format="json") for _ in range(6)
        ]

        status_codes = [r.status_code for r in responses]
        assert 429 in status_codes, f"Expected 429 in {status_codes}"


@pytest.mark.django_db
class TestRegisterRateLimit:

    def test_register_throttled_after_limit(self, api_client, db, settings):
        """After 5 register attempts, the endpoint returns 429."""
        settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["register"] = "3/minute"

        def make_register_request(n):
            return api_client.post(
                "/api/auth/register/",
                {
                    "username": f"newuser{n}",
                    "email": f"newuser{n}@example.com",
                    "password": "SecurePass123!",
                    "tenant_name": f"Business {n}",
                },
                format="json",
            )

        responses = [make_register_request(i) for i in range(4)]
        status_codes = [r.status_code for r in responses]
        assert 429 in status_codes, f"Expected 429 in {status_codes}"
