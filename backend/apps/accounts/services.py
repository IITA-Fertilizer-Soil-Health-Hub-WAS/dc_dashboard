"""Account helpers shared between the Auth0 social adapter and management commands."""
from __future__ import annotations

from apps.projects.models import Project
from apps.rbac.models import Membership, Role


def platform_admin_exists() -> bool:
    """True once any Platform Admin (Django superuser) exists."""
    from .models import User

    return User.objects.filter(is_superuser=True).exists()


def promote_to_platform_admin(user, *, password: str | None = None):
    """Grant Platform Admin (Django superuser) to an existing account, idempotently.

    Sets the full superuser/staff/active/verified flag combination and stamps
    approved_at once. Pass ``password`` only on the email/password bootstraps
    (first-run web form, ``bootstrap_admin`` command); the post-SSO claim leaves
    the Auth0 password untouched. Callers own the ``platform_admin_exists()`` gate
    and race guard — this only mutates the user.
    """
    from django.utils import timezone

    user.is_superuser = True
    user.is_staff = True
    user.is_active = True
    user.email_verified = True
    user.approved_at = user.approved_at or timezone.now()
    if password:
        user.set_password(password)
    user.save()
    return user


def claim_admin_available(user) -> bool:
    """Whether `user` may claim Platform Admin via the in-app bootstrap.

    Open only while the system has no Platform Admin at all, and only to an
    authenticated, active account (the first Auth0 login auto-activates for
    exactly this — see the social adapter). Closes permanently after the first
    claim, so it cannot be used to escalate on an established instance.
    """
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and not platform_admin_exists()
    )


def sync_memberships_from_eia_apps(user) -> int:
    """Create VIEWER memberships for each project in the user's legacy_eia_apps.

    Idempotent. Returns the number of memberships created. Unknown project codes
    are ignored (a Platform Admin can grant access explicitly later). Higher roles
    (Coordinator) are always admin-assigned, never inferred.
    """
    apps = user.legacy_eia_apps or {}
    codes = apps.keys() if isinstance(apps, dict) else apps
    created = 0
    for code in codes:
        uc = Project.objects.filter(code=code).first()
        if uc is None:
            continue
        _, was_created = Membership.objects.get_or_create(
            user=user, project=uc, role=Role.VIEWER
        )
        created += int(was_created)
    return created
