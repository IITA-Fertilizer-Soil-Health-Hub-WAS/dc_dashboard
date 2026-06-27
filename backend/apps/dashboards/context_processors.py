"""Template context shared across all pages (the app shell needs it everywhere)."""
from __future__ import annotations

from apps.rbac.permissions import can_manage_access, pending_users, visible_use_cases


def navigation(request):
    """Expose nav data for the single green app rail:

    * the user's accessible use cases (monitoring mode), and
    * the management console sections (Manage mode, staff only).
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"nav_use_cases": [], "console_groups": []}

    from apps.fieldwork.models import UnitAssignment
    from apps.rbac.models import Role, UseCaseMembership

    # Anyone holding the enumerator role gets the link as their entry point —
    # not only once they already have an assignment (otherwise a freshly
    # onboarded enumerator sees no path to their own work).
    show_my_assignments = (
        UseCaseMembership.objects.filter(user=user, role=Role.ENUMERATOR).exists()
        or UnitAssignment.objects.filter(enumerator=user).exists()
    )

    from apps.console.registry import REGISTRY, grouped_for

    # Staff see all console sections; coordinators see a read-only, scoped subset
    # (their projects' configuration + field data).
    console_groups = grouped_for(user)
    active_group = None
    if console_groups:
        match = getattr(request, "resolver_match", None)
        if match is not None and match.app_name == "console":
            current = REGISTRY.get(match.kwargs.get("key"))
            active_group = current.group if current else None
    from apps.accounts.services import claim_admin_available

    manages_access = can_manage_access(user)
    pending_count = 0
    if manages_access:
        from apps.rbac.models import UseCaseAccessRequest
        from apps.rbac.permissions import grantable_scopes

        grant_uc = grantable_scopes(user)["use_cases"].values_list("id", flat=True)
        pending_count = pending_users().count() + UseCaseAccessRequest.objects.filter(
            status=UseCaseAccessRequest.Status.PENDING, use_case_id__in=list(grant_uc)
        ).count()

    # The sidebar offers a project dropdown (quick jump); the Projects page is the
    # scalable directory (search / filter / paginate). Cap the dropdown so it stays
    # sane for a hub operator with very many projects.
    visible = visible_use_cases(user)
    nav_use_cases = list(visible.order_by("code")[:200])
    nav_use_cases_total = visible.count()
    return {
        "nav_use_cases": nav_use_cases,
        "nav_use_cases_total": nav_use_cases_total,
        "console_groups": console_groups,
        "console_active_group": active_group,
        "can_manage_access": manages_access,
        "pending_approvals_count": pending_count,
        "show_claim_admin": claim_admin_available(user),
        "show_my_assignments": show_my_assignments,
    }
