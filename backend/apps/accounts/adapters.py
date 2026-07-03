"""Allauth adapters — Auth0 is the only registration / sign-in path.

Local email+password signup and login are turned off (see settings + the
redirects in eia_dcmt/urls.py). Authentication happens via Auth0 (OIDC); this
app owns authorization (project roles/memberships).

On Auth0 login the social adapter: activates the user (Auth0 vetted identity),
snapshots the `eia_apps` / `sub` claims, and syncs VIEWER memberships so the user
immediately sees the projects Auth0 granted them. Coordinator
roles remain admin-assigned.
"""
from __future__ import annotations

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

from .services import sync_memberships_from_eia_apps

# Require approval even for Auth0-authenticated users: a first-time Auth0 login
# provisions the account but leaves it inactive (allauth shows the "account
# inactive" page) until it is approved in-app on the Team & access screen (any
# coordinator can approve into a scope they own; see apps.dashboards.team). Set
# to False to trust the Auth0 identity and activate on first login instead.
REQUIRE_ADMIN_APPROVAL_FOR_AUTH0 = True


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request) -> bool:
        # No local (email/password) self-registration — Auth0 only.
        return False


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin) -> bool:
        # Auth0 users may sign up (first login provisions the account).
        return True

    def _apply_claims(self, user, extra: dict) -> list[str]:
        changed: list[str] = []
        eia_apps = extra.get("eia_apps")
        sub = extra.get("sub")
        if eia_apps is not None and user.legacy_eia_apps != eia_apps:
            user.legacy_eia_apps = eia_apps
            changed.append("legacy_eia_apps")
        if sub and user.auth0_sub != sub:
            user.auth0_sub = sub
            changed.append("auth0_sub")
        return changed

    def pre_social_login(self, request, sociallogin) -> None:
        """Runs for every Auth0 login (new and returning). Snapshot claims onto
        an already-existing user; brand-new users are finished in save_user."""
        user = sociallogin.user
        if not user.pk:
            return
        changed = self._apply_claims(user, sociallogin.account.extra_data or {})
        if changed:
            user.save(update_fields=changed)
        sync_memberships_from_eia_apps(user)

    def save_user(self, request, sociallogin, form=None):
        """Finish provisioning a first-time Auth0 user."""
        from .models import User
        from .services import platform_admin_exists

        user = super().save_user(request, sociallogin, form)
        self._apply_claims(user, sociallogin.account.extra_data or {})
        user.email_verified = True  # Auth0 verified the email
        # Auth0 vetted the identity, so the account is active (may log in) — but
        # it stays UN-approved until an admin reviews the profile the user is now
        # required to fill. Authorization keys off is_approved, not is_active.
        user.is_active = True
        user.is_approved = not REQUIRE_ADMIN_APPROVAL_FOR_AUTH0
        # Bootstrap: the very first account on a system with no Platform Admin is
        # auto-approved so it can reach the in-app "claim Platform Admin" page.
        # Only the first account — everyone after stays pending until approved.
        first_account = not User.objects.exclude(pk=user.pk).exists()
        if first_account and not platform_admin_exists():
            user.is_approved = True
        user.save()
        sync_memberships_from_eia_apps(user)
        return user
