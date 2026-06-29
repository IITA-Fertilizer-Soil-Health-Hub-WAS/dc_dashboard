"""Template context available on every page, including unauthenticated ones."""
from __future__ import annotations

from django.conf import settings


def site(request):
    """The configurable product name (settings.SITE_NAME) for titles + branding."""
    return {"SITE_NAME": settings.SITE_NAME}
