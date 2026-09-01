"""Hard-gate the platform on profile completion.

An authenticated user whose identity profile isn't complete can't use anything
until they finish it: every request redirects to the profile form, except the
form itself, the auth flow (so login/logout/OIDC callback work), Django admin
(a staff safety valve), and health/static assets.

Gated by ``REQUIRE_COMPLETE_PROFILE`` (on in prod, off in tests). Fail-soft: a
DB hiccup never locks everyone out. Once complete, a session flag skips the
check so it costs one query per session, not per request.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse


class ProfileCompletionMiddleware:
    # /api/ is exempt: token clients aren't humans filling a profile form.
    EXEMPT_PREFIXES = ("/accounts/", "/api/", "/static/", "/media/", "/healthz", "/admin/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._should_gate(request):
            target = reverse("profile")
            # HTMX: tell it to do a real full-page redirect, not swap the profile
            # document into a small partial slot.
            if request.headers.get("HX-Request"):
                resp = HttpResponse(status=204)
                resp["HX-Redirect"] = target
                return resp
            messages.info(request, "Complete your profile to start using the platform.")
            return redirect(target)
        return self.get_response(request)

    def _should_gate(self, request) -> bool:
        if not getattr(settings, "REQUIRE_COMPLETE_PROFILE", True):
            return False
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return False
        if request.session.get("profile_complete"):
            return False
        path = request.path
        if path.startswith(reverse("profile")) or any(
            path.startswith(p) for p in self.EXEMPT_PREFIXES
        ):
            return False
        try:
            from apps.accounts.models import UserProfile

            complete = UserProfile.objects.filter(
                user=user, completed_at__isnull=False
            ).exists()
        except Exception:  # noqa: BLE001 — never lock everyone out on a DB error
            return False
        if complete:
            request.session["profile_complete"] = True
            return False
        return True
