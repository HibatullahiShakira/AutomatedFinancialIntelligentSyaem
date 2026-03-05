import os
import django
from django.conf import settings

# Ensure Django is set up before running tests
def pytest_configure() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    if not settings.configured:
        django.setup()
