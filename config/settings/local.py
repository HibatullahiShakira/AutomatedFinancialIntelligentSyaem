# noqa: F403  # wildcard import is intentional for settings
from .base import *

# Development-specific settings
DEBUG = True

# Use console email backend for development
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Additional development overrides can go here (e.g. LocalStack endpoints)
