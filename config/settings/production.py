# noqa: F403  # wildcard import used for settings inheritance
from .base import *

import os
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

DEBUG = False

# Security hardening
SECURE_HSTS_SECONDS = 31536000
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Static files via WhiteNoise
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Sentry integration
sentry_sdk.init(dsn=os.environ.get("SENTRY_DSN", ""), integrations=[DjangoIntegration()])
