"""Template context shared across all pages (the app shell needs it everywhere)."""
from __future__ import annotations

from apps.rbac.permissions import can_manage_access, pending_users, visible_projects


def navigation(request):
    """Expose nav data for the single green app rail:

    * the user's accessible projects (monitoring mode), and
    * the management console sections (Manage mode, staff only).
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"nav_projects": [], "console_groups": []}

    from apps.fieldwork.models import UnitAssignment
    from apps.rbac.models import ProjectMembership, Role

    # Anyone holding the enumerator role gets the link as their entry point —
    # not only once they already have an assignment (otherwise a freshly
    # onboarded enumerator sees no path to their own work).
    show_my_assignments = (
        ProjectMembership.objects.filter(user=user, role=Role.ENUMERATOR).exists()
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
        from apps.rbac.models import ProjectAccessRequest
        from apps.rbac.permissions import grantable_scopes

        grant_uc = grantable_scopes(user)["projects"].values_list("id", flat=True)
        pending_count = pending_users().count() + ProjectAccessRequest.objects.filter(
            status=ProjectAccessRequest.Status.PENDING, project_id__in=list(grant_uc)
        ).count()

    # The sidebar offers a project dropdown (quick jump); the Projects page is the
    # scalable directory (search / filter / paginate). Cap the dropdown so it stays
    # sane for a hub operator with very many projects.
    visible = visible_projects(user)
    nav_projects = list(visible.order_by("code")[:200])
    nav_projects_total = visible.count()

    # Project = workspace: the project the user is currently working in (sticky in
    # session, validated against what they may still see). The sidebar scopes to it.
    active_uc = None
    code = request.session.get("active_project") if hasattr(request, "session") else None
    if code:
        active_uc = visible.filter(code=code).first()

    # Gate-2 validators (agronomic QC sign-off) get a dedicated queue link in the
    # active project.
    can_validate_active = False
    if active_uc is not None:
        from apps.rbac.permissions import user_can

        can_validate_active = user_can(user, "final_approve", active_uc)

    from apps.accounts.models import UserProfile

    profile_complete = UserProfile.objects.filter(
        user=user, completed_at__isnull=False
    ).exists()

    return {
        "nav_projects": nav_projects,
        "nav_projects_total": nav_projects_total,
        "active_uc": active_uc,
        "can_validate_active": can_validate_active,
        "profile_incomplete": not profile_complete,
        "console_groups": console_groups,
        "console_active_group": active_group,
        "can_manage_access": manages_access,
        "pending_approvals_count": pending_count,
        "show_claim_admin": claim_admin_available(user),
        "show_my_assignments": show_my_assignments,
    }
