"""Test settings — fast, isolated, no external services."""
from __future__ import annotations

from .base import *  # noqa: F401,F403

DEBUG = False

# Use SQLite for fast, dependency-free unit tests. Postgres-specific behaviour
# (jsonb/GIN/ArrayField) is exercised in integration tests against Postgres.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
WHITENOISE_USE_FINDERS = True  # avoid "no staticfiles dir" warning (none collected in tests)
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
CELERY_TASK_ALWAYS_EAGER = True
ONA_TOKEN = "test-token"
