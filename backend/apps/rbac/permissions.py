"""Authorization facade.

`user_can(user, action, use_case)` is the single entry point for permission
checks across views, templates, DRF, and the review state machine. It maps
abstract actions to the roles allowed to perform them, scoped to a use case.
Keeping this in one place means the review state machine, the dashboards, and
the API all agree on who can do what.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Q

from .models import Role, UseCaseMembership

if TYPE_CHECKING:
    from apps.usecases.models import UseCase

# Action -> set of use-case-scoped roles that may perform it.
# Coordinator roles share the trial-coordinator powers, just at a wider scope
# (region/country grants cascade to use cases — see roles_for).
COORDINATORS = {Role.TRIAL_COORDINATOR, Role.COUNTRY_COORDINATOR, Role.REGIONAL_COORDINATOR}
# Two-level review: Trial/Country coordinators do the first-level review and
# endorsement (Gate 1); only a Regional Coordinator gives final validation (Gate 2).
GATE1_REVIEWERS = {Role.TRIAL_COORDINATOR, Role.COUNTRY_COORDINATOR}
GATE2_VALIDATOR = {Role.REGIONAL_COORDINATOR}

# Platform Admin (superuser) bypasses this table entirely. Coordinators are the
# reviewers — they hold the domain expertise and run the review workflow end to
# end (there is no separate domain-expert / quality role).
ACTION_ROLES: dict[str, set[str]] = {
    # Read access to a use case's data/dashboards.
    "view": {Role.VIEWER, Role.ENUMERATOR} | COORDINATORS,
    # Review workflow — open / triage / correct is shared by all coordinators.
    "open_review": COORDINATORS,
    "decline": COORDINATORS,
    "request_edit": COORDINATORS,
    "edit": COORDINATORS,
    "reopen": COORDINATORS,
    "resolve_flag": COORDINATORS,
    # Gate 1: first-level endorsement by Trial/Country coordinators.
    "endorse": GATE1_REVIEWERS,
    # Gate 2: final validation reserved for the Regional Coordinator.
    "final_approve": GATE2_VALIDATOR,
    # Operations — pulling from the collection server.
    "sync": COORDINATORS,
}

# Actions only the Platform Admin may perform (no use-case scope).
GLOBAL_ADMIN_ACTIONS: set[str] = {"manage_config", "manage_users", "manage_usecases"}


def roles_for(user, use_case: UseCase) -> set[str]:
    """All roles a user holds for a use case, including cascaded country/region grants.

    A grant on the use case's country (or region) confers the same role as a direct
    use-case grant — that's how a Country/Regional Coordinator gets coordinator
    powers across every use case beneath them without per-use-case rows.
    """
    if not user.is_authenticated:
        return set()
    scope = Q(use_case=use_case)
    if use_case.country_id:
        scope |= Q(country_id=use_case.country_id)
        if use_case.country.region_id:
            scope |= Q(region_id=use_case.country.region_id)
    return set(
        UseCaseMembership.objects.filter(scope, user=user).values_list("role", flat=True)
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

    held = roles_for(user, use_case)

    # Gate 2 fallback: a Country Coordinator may give final validation only when
    # no Regional Coordinator covers this use case — so a use case without a
    # Regional assigned doesn't stall, while a Regional always takes precedence.
    if (
        action == "final_approve"
        and Role.COUNTRY_COORDINATOR in held
        and not _regional_validator_exists(use_case)
    ):
        return True

    return bool(held & allowed_roles)


def _regional_validator_exists(use_case) -> bool:
    """Whether any active Regional Coordinator has authority over this use case."""
    scope = Q(use_case=use_case)
    if use_case.country_id:
        scope |= Q(country_id=use_case.country_id)
        if use_case.country.region_id:
            scope |= Q(region_id=use_case.country.region_id)
    return UseCaseMembership.objects.filter(
        scope, role=Role.REGIONAL_COORDINATOR, user__is_active=True
    ).exists()


def visible_use_cases(user):
    """Use cases a user may view — replaces the R `eia_apps ∩ active_use_case_list`.

    Platform Admin sees all active use cases; everyone else sees only use cases
    where they hold a membership.
    """
    from apps.usecases.models import UseCase

    if not getattr(user, "is_authenticated", False):
        return UseCase.objects.none()
    if getattr(user, "is_platform_admin", False):
        return UseCase.objects.filter(is_active=True)  # hub operator spans tenants
    own_org = getattr(user, "organization_id", None)
    # Region/country grants cascade only within the user's own institution — a
    # whole region of another org is never shared this way.
    cascade = Q(country__memberships__user=user) | Q(country__region__memberships__user=user)
    if own_org:
        cascade &= Q(organization_id=own_org)
    # A direct use-case membership grants visibility even across the org
    # boundary: that is exactly how an owner shares one project with an outside
    # collaborator (see team.team_invite). Everything else stays in-tenant.
    return UseCase.objects.filter(
        Q(memberships__user=user) | cascade, is_active=True
    ).distinct()


def organization_of(scope_obj):
    """The Organization id that owns a scope object (Region / Country / UseCase)."""
    from apps.usecases.models import Country, Region, UseCase

    if isinstance(scope_obj, Region):
        return scope_obj.organization_id
    if isinstance(scope_obj, Country):
        return scope_obj.region.organization_id
    if isinstance(scope_obj, UseCase):
        return scope_obj.organization_id
    return None


# ---------------------------------------------------------------------------
# Delegated administration: coordinators grant access within their own scope.
#
# Two independent limits bound every grant:
#   1. SCOPE — you may only grant at a scope your coordinator authority covers
#      (region covers its countries + use cases; country covers its use cases).
#   2. ROLE CEILING — you may only assign a role at or below your own rank, and
#      never Platform Admin (that is the Django superuser flag, set elsewhere).
# can_grant() enforces both and is the single check every POST must pass.
# ---------------------------------------------------------------------------

# Higher number = more authority. Quality roles sit above field roles but below
# coordinators. Platform Admin is off the scale and not grantable via the UI.
ROLE_RANK: dict[str, int] = {
    Role.PLATFORM_ADMIN: 100,
    Role.REGIONAL_COORDINATOR: 80,
    Role.COUNTRY_COORDINATOR: 70,
    Role.TRIAL_COORDINATOR: 60,
    Role.ENUMERATOR: 20,
    Role.VIEWER: 10,
}


def _authority(user) -> tuple[set, set, set]:
    """The (region_ids, country_ids, use_case_ids) a user has coordinator authority over."""
    region_ids: set = set()
    country_ids: set = set()
    uc_ids: set = set()
    rows = UseCaseMembership.objects.filter(user=user, role__in=COORDINATORS).values(
        "region_id", "country_id", "use_case_id"
    )
    for r in rows:
        if r["region_id"]:
            region_ids.add(r["region_id"])
        elif r["country_id"]:
            country_ids.add(r["country_id"])
        elif r["use_case_id"]:
            uc_ids.add(r["use_case_id"])
    return region_ids, country_ids, uc_ids


def _max_grant_rank(user) -> int:
    """The highest role rank a user is entitled to confer."""
    if getattr(user, "is_platform_admin", False):
        return ROLE_RANK[Role.PLATFORM_ADMIN]
    roles = UseCaseMembership.objects.filter(user=user, role__in=COORDINATORS).values_list(
        "role", flat=True
    )
    return max((ROLE_RANK.get(r, 0) for r in roles), default=0)


def can_manage_access(user) -> bool:
    """Whether a user can administer access at all (Platform Admin or any coordinator)."""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return False
    if getattr(user, "is_platform_admin", False):
        return True
    return UseCaseMembership.objects.filter(user=user, role__in=COORDINATORS).exists()


def grantable_roles(user) -> list[str]:
    """Roles `user` may assign — at or below their own rank, never Platform Admin."""
    cap = _max_grant_rank(user)
    if cap <= 0:
        return []
    return [
        r for r in Role.values
        if r != Role.PLATFORM_ADMIN and ROLE_RANK.get(r, 999) <= cap
    ]


def can_grant_at(user, scope_obj) -> bool:
    """Whether `user`'s coordinator authority covers this scope (Region/Country/UseCase)."""
    if getattr(user, "is_platform_admin", False):
        return True
    from apps.usecases.models import Country, Region, UseCase

    region_ids, country_ids, uc_ids = _authority(user)
    if isinstance(scope_obj, Region):
        return scope_obj.id in region_ids
    if isinstance(scope_obj, Country):
        return scope_obj.id in country_ids or scope_obj.region_id in region_ids
    if isinstance(scope_obj, UseCase):
        if scope_obj.id in uc_ids:
            return True
        if scope_obj.country_id and scope_obj.country_id in country_ids:
            return True
        return bool(
            scope_obj.country_id
            and scope_obj.country.region_id in region_ids
        )
    return False


def can_grant(user, scope_obj, role: str) -> bool:
    """The single authority check: may `user` grant `role` at `scope_obj`?"""
    if role == Role.PLATFORM_ADMIN:
        return False
    if not can_manage_access(user):
        return False
    if ROLE_RANK.get(role, 999) > _max_grant_rank(user):
        return False
    return can_grant_at(user, scope_obj)


def grantable_scopes(user) -> dict:
    """Scopes (regions/countries/use cases) `user` may grant within, for menus."""
    from apps.usecases.models import Country, Region, UseCase

    if getattr(user, "is_platform_admin", False):
        return {
            "regions": Region.objects.all(),
            "countries": Country.objects.select_related("region").all(),
            "use_cases": UseCase.objects.filter(is_active=True).select_related("country"),
        }
    region_ids, country_ids, uc_ids = _authority(user)
    return {
        "regions": Region.objects.filter(id__in=region_ids),
        "countries": Country.objects.select_related("region").filter(
            Q(id__in=country_ids) | Q(region_id__in=region_ids)
        ),
        "use_cases": UseCase.objects.filter(
            Q(id__in=uc_ids)
            | Q(country_id__in=country_ids)
            | Q(country__region_id__in=region_ids),
            is_active=True,
        ).select_related("country"),
    }


def manageable_memberships(user):
    """Memberships `user` may view/revoke — those whose scope their authority covers."""
    if not can_manage_access(user):
        return UseCaseMembership.objects.none()
    qs = UseCaseMembership.objects.select_related(
        "user", "use_case", "country", "region", "granted_by"
    )
    if getattr(user, "is_platform_admin", False):
        return qs
    region_ids, country_ids, uc_ids = _authority(user)
    return qs.filter(
        Q(region_id__in=region_ids)
        | Q(country_id__in=country_ids)
        | Q(country__region_id__in=region_ids)
        | Q(use_case_id__in=uc_ids)
        | Q(use_case__country_id__in=country_ids)
        | Q(use_case__country__region_id__in=region_ids)
    )


def pending_users():
    """Users awaiting approval (inactive). Visible to any access manager."""
    from apps.accounts.models import User

    return User.objects.filter(is_active=False).order_by("created_at")
