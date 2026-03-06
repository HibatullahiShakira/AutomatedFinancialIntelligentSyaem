"""
Shared pytest fixtures and configuration.
"""
import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear Django cache between tests to prevent throttle state leaking."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def use_console_email_backend(settings):
    """Use console email backend in tests so no real emails are sent."""
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
