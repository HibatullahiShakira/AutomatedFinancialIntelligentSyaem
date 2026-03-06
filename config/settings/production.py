from .base import *  # noqa: F403  # wildcard import used for settings inheritance

import os
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

DEBUG = False

# Redis cache for throttling, token revocation blacklist, and session caching
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
        "KEY_PREFIX": "amss",
    }
}

# Security hardening
SECURE_HSTS_SECONDS = 31536000
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Static files via WhiteNoise
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Sentry integration
sentry_sdk.init(dsn=os.environ.get("SENTRY_DSN", ""), integrations=[DjangoIntegration()])
