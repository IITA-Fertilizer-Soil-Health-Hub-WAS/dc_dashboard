from __future__ import annotations

from django.conf import settings
from django.contrib.auth.views import LoginView


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
        ctx["next"] = self.request.GET.get("next", "")
        return ctx
