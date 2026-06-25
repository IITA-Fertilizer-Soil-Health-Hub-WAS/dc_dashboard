"""Authorization facade.

`user_can(user, action, use_case)` is the single entry point for permission
checks across views, templates, DRF, and the review state machine. It maps
abstract actions to the roles allowed to perform them, scoped to a use case.
Keeping this in one place means the review state machine, the dashboards, and
the API all agree on who can do what.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .models import Role, UseCaseMembership

if TYPE_CHECKING:
    from apps.usecases.models import UseCase

# Action -> set of use-case-scoped roles that may perform it.
# Platform Admin (superuser) bypasses this table entirely.
ACTION_ROLES: dict[str, set[str]] = {
    # Read access to a use case's data/dashboards.
    "view": {Role.VIEWER, Role.ENUMERATOR, Role.TRIAL_COORDINATOR, Role.QUALITY_CHECK},
    # Review workflow.
    "open_review": {Role.TRIAL_COORDINATOR, Role.QUALITY_CHECK},
    "decline": {Role.TRIAL_COORDINATOR},
    "request_edit": {Role.TRIAL_COORDINATOR},
    "edit": {Role.TRIAL_COORDINATOR},
    "qc_approve": {Role.QUALITY_CHECK},
    "reopen": {Role.TRIAL_COORDINATOR, Role.QUALITY_CHECK},
    "resolve_flag": {Role.TRIAL_COORDINATOR, Role.QUALITY_CHECK},
    # Operations.
    "sync": {Role.TRIAL_COORDINATOR},
}

# Actions only the Platform Admin may perform (no use-case scope).
GLOBAL_ADMIN_ACTIONS: set[str] = {"manage_config", "manage_users", "manage_usecases"}


def roles_for(user, use_case: UseCase) -> set[str]:
    """All roles a user holds within a given use case."""
    if not user.is_authenticated:
        return set()
    return set(
        UseCaseMembership.objects.filter(user=user, use_case=use_case).values_list(
            "role", flat=True
        )
    )


def user_can(user, action: str, use_case: UseCase | None = None) -> bool:
    """Return True if `user` may perform `action` (optionally within `use_case`)."""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return False

    # Platform Admin can do everything.
    if getattr(user, "is_platform_admin", False):
        return True

    if action in GLOBAL_ADMIN_ACTIONS:
        return False  # only Platform Admin, handled above

    allowed_roles = ACTION_ROLES.get(action)
    if allowed_roles is None:
        raise ValueError(f"Unknown action: {action!r}")

    if use_case is None:
        return False  # scoped actions require a use case

    return bool(roles_for(user, use_case) & allowed_roles)


def visible_use_cases(user):
    """Use cases a user may view — replaces the R `eia_apps ∩ active_use_case_list`.

    Platform Admin sees all active use cases; everyone else sees only use cases
    where they hold a membership.
    """
    from apps.usecases.models import UseCase

    if not getattr(user, "is_authenticated", False):
        return UseCase.objects.none()
    if getattr(user, "is_platform_admin", False):
        return UseCase.objects.filter(is_active=True)
    return UseCase.objects.filter(is_active=True, memberships__user=user).distinct()
