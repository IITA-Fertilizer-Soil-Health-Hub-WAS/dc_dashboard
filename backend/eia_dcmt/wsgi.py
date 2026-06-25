"""WSGI config for eia_dcmt."""
from __future__ import annotations

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "eia_dcmt.settings.prod")

application = get_wsgi_application()
