from .base import *

# Development-specific settings
DEBUG = True

# Use console email backend for development
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Additional development overrides can go here (e.g. LocalStack endpoints)
