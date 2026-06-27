from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .services import claim_admin_available, platform_admin_exists


class LoginLandingView(LoginView):
    """Single sign-in page offering BOTH paths:

    * "Continue with Auth0" (the primary path for everyone), and
    * an email/password form for Platform Admins / staff.

    Regular users provisioned via Auth0 have an unusable password, so the form
    only works for accounts that have a password set (admins) and, like all
    logins, only for active users. Authentication uses the ModelBackend.
    """

    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["auth0_configured"] = settings.AUTH0_CONFIGURED
        ctx["auth0_login_url"] = settings.AUTH0_LOGIN_URL
        # Entra ID is an optional fallback — only surfaced when configured.
        ctx["entra_configured"] = settings.ENTRA_CONFIGURED
        ctx["entra_login_url"] = settings.ENTRA_LOGIN_URL
        ctx["next"] = self.request.GET.get("next", "")
        return ctx


@login_required
@require_http_methods(["GET", "POST"])
def claim_admin(request):
    """One-time in-app bootstrap: the first user claims Platform Admin.

    Available only while no Platform Admin exists; closes permanently after the
    first claim. The POST re-checks inside a transaction so two simultaneous
    claims can't both win.
    """
    if not claim_admin_available(request.user):
        if platform_admin_exists():
            messages.info(request, "A Platform Admin already exists.")
        return redirect("dashboards:index")

    if request.method == "POST":
        with transaction.atomic():
            if platform_admin_exists():
                messages.info(request, "A Platform Admin already exists.")
                return redirect("dashboards:index")
            user = request.user
            user.is_superuser = True
            user.is_staff = True
            user.is_active = True
            user.approved_at = user.approved_at or timezone.now()
            user.save(update_fields=[
                "is_superuser", "is_staff", "is_active", "approved_at", "updated_at",
            ])
        messages.success(
            request, "You are now the Platform Admin. You can approve users and "
            "manage everything from here."
        )
        return redirect("dashboards:index")

    return render(request, "accounts/claim_admin.html", {})
