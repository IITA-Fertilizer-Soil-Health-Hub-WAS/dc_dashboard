"""Template context available on every page, including unauthenticated ones."""
from __future__ import annotations

from django.conf import settings


def site(request):
    """The configurable product name (settings.SITE_NAME) for titles + branding,
    and the platform admin contact shown wherever a user needs to reach an
    operator (e.g. the 'no institution onboarded yet' registration state)."""
    return {
        "SITE_NAME": settings.SITE_NAME,
        "PLATFORM_ADMIN_EMAIL": settings.PLATFORM_ADMIN_EMAIL,
    }
