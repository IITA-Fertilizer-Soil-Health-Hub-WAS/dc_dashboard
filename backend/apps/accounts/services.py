"""Account helpers shared between the Auth0 social adapter and management commands."""
from __future__ import annotations

from apps.rbac.models import Role, UseCaseMembership
from apps.usecases.models import UseCase


def sync_memberships_from_eia_apps(user) -> int:
    """Create VIEWER memberships for each use case in the user's legacy_eia_apps.

    Idempotent. Returns the number of memberships created. Unknown use-case codes
    are ignored (a Platform Admin can grant access explicitly later). Higher roles
    (Coordinator / Quality Check) are always admin-assigned, never inferred.
    """
    apps = user.legacy_eia_apps or {}
    codes = apps.keys() if isinstance(apps, dict) else apps
    created = 0
    for code in codes:
        uc = UseCase.objects.filter(code=code).first()
        if uc is None:
            continue
        _, was_created = UseCaseMembership.objects.get_or_create(
            user=user, use_case=uc, role=Role.VIEWER
        )
        created += int(was_created)
    return created
