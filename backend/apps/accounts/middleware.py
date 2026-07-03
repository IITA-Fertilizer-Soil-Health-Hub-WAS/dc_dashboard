"""Approval gate: a logged-in but not-yet-approved user may only reach the
profile form (which they must submit) and the 'pending approval' page.

The flow this enforces:
  1. Auth0 provisions the account active-but-unapproved.
  2. The user lands here and is redirected to fill their profile.
  3. Once the profile is submitted, they see the pending page until an admin
     reviews that profile and approves them.
Superusers and already-approved users pass straight through.
"""
from __future__ import annotations

from django.shortcuts import redirect
from django.urls import Resolver404, resolve, reverse

# URL names a pending user may always reach (besides static/media, handled by
# path prefix). Everything else redirects into the gate.
_ALLOWED = {"profile", "pending", "claim_admin", "create_admin", "login"}


class ApprovalGateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated or not getattr(user, "awaiting_approval", False):
            return self.get_response(request)

        path = request.path
        # Let auth/allauth, health, static and media through so the user can log
        # out and the page can load its assets.
        if path.startswith(("/accounts/", "/static/", "/media/", "/healthz")):
            return self.get_response(request)

        try:
            match = resolve(path)
        except Resolver404:
            match = None
        if match is not None and match.url_name in _ALLOWED:
            return self.get_response(request)

        # Not approved and trying to use the app: route to the right waiting step.
        from apps.accounts.models import UserProfile

        submitted = UserProfile.objects.filter(
            user=user, completed_at__isnull=False
        ).exists()
        return redirect(reverse("pending") if submitted else reverse("profile"))
