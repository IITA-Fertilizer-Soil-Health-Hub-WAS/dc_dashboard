"""Local development settings."""
from __future__ import annotations

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Console email backend so verification links print to the terminal in dev.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Run Celery tasks inline unless a broker is explicitly configured.
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=True)

# Let WhiteNoise serve static straight from app/finders so the Docker dev
# container (gunicorn) shows admin CSS/JS without a collectstatic step.
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = True
