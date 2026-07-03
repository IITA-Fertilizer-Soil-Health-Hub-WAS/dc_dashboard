"""Team & Access — in-app user approval and scoped role granting.

Replaces the Django-admin path so coordinators never touch /admin/. A coordinator
can approve pending users and grant access, but only within the scope and up to
the role rank their own coordinator membership confers. Every mutating request is
re-validated against ``rbac.permissions.can_grant`` server-side, so a tampered
form can never escalate beyond the granter's authority.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.projects.models import Project
from apps.rbac.models import Role, UseCaseAccessRequest, UseCaseMembership
from apps.rbac.permissions import (
    can_grant,
    can_manage_access,
    grantable_roles,
    grantable_scopes,
    manageable_memberships,
    organization_of,
    pending_users,
)

# Maps the scope <select> token prefix to the membership FK field.
_SCOPE_FIELD = {"region": "region", "country": "country", "project": "project"}


def _require_access(user):
    if not can_manage_access(user):
        raise PermissionDenied("You do not manage access.")


def _scope_options(user) -> list[dict]:
    """Flat, grouped list of grantable scopes for the <select> (token + label)."""
    scopes = grantable_scopes(user)
    opts: list[dict] = []
    for r in scopes["regions"]:
        opts.append({"value": f"region:{r.pk}", "label": f"Region · {r.name}"})
    for c in scopes["countries"]:
        opts.append({"value": f"country:{c.pk}", "label": f"Country · {c.name} ({c.region.name})"})
    for uc in scopes["projects"]:
        opts.append({"value": f"project:{uc.pk}", "label": f"Project · {uc.code}"})
    return opts


def _role_options(user) -> list[dict]:
    labels = dict(Role.choices)
    return [{"value": r, "label": labels[r]} for r in grantable_roles(user)]


def _project_options(user) -> list[dict]:
    """Only the use-case scopes (collaboration is shared per project, never wider)."""
    return [
        {"value": f"project:{uc.pk}", "label": uc.code}
        for uc in grantable_scopes(user)["projects"]
    ]


def _resolve_scope(token: str):
    """Parse a 'level:pk' token into a scope object, or None if invalid."""
    level, _, pk = (token or "").partition(":")
    if level not in _SCOPE_FIELD:
        return None
    from apps.projects.models import Country, Project, Region

    model = {"region": Region, "country": Country, "project": Project}[level]
    return model.objects.filter(pk=pk).first()


@login_required
def team(request):
    """The Team & Access dashboard: pending approvals + the access you administer."""
    _require_access(request.user)
    memberships = manageable_memberships(request.user).order_by(
        "user__email", "role"
    )
    # Existing users you can grant to: only your own institution's people (a hub
    # operator with no org spans all). Pending users have no org yet.
    active = User.objects.filter(is_active=True)
    if request.user.organization_id:
        active = active.filter(organization_id=request.user.organization_id)
    # Self-service join requests on the use cases this person administers.
    grantable_uc_ids = grantable_scopes(request.user)["projects"].values_list("id", flat=True)
    access_requests = (
        UseCaseAccessRequest.objects.filter(
            status=UseCaseAccessRequest.Status.PENDING, project_id__in=list(grantable_uc_ids)
        )
        .select_related("user", "project")
        .order_by("created_at")
    )
    ctx = {
        "pending": pending_users(),
        "memberships": memberships,
        "access_requests": access_requests,
        "scope_options": _scope_options(request.user),
        "role_options": _role_options(request.user),
        "project_options": _project_options(request.user),
        "active_users": active.order_by("email"),
    }
    return render(request, "dashboards/team.html", ctx)


@require_POST
@login_required
def team_request_decision(request):
    """Approve (grant a role) or decline a self-service access request."""
    _require_access(request.user)
    req = get_object_or_404(
        UseCaseAccessRequest, pk=request.POST.get("request"),
        status=UseCaseAccessRequest.Status.PENDING,
    )
    decision = request.POST.get("decision")

    if decision == "approve":
        role = request.POST.get("role") or Role.VIEWER
        if role not in dict(Role.choices) or not can_grant(request.user, req.project, role):
            raise PermissionDenied("That grant exceeds your authority.")
        UseCaseMembership.objects.get_or_create(
            user=req.user, project=req.project, role=role,
            defaults={"granted_by": request.user},
        )
        if not req.user.organization_id and req.project.organization_id:
            req.user.organization_id = req.project.organization_id
            req.user.save(update_fields=["organization", "updated_at"])
        req.status = UseCaseAccessRequest.Status.APPROVED
        messages.success(request, f"Granted {req.user.email} {role} on {req.project.code}.")
    elif decision == "decline":
        # Only someone with authority over the use case may decline it.
        if not can_grant(request.user, req.project, Role.VIEWER):
            raise PermissionDenied("Outside your authority.")
        req.status = UseCaseAccessRequest.Status.DECLINED
        messages.info(request, f"Declined {req.user.email}'s request for {req.project.code}.")
    else:
        return redirect("dashboards:team")

    req.decided_by = request.user
    req.decided_at = timezone.now()
    req.save(update_fields=["status", "decided_by", "decided_at", "updated_at"])
    return redirect("dashboards:team")


@require_POST
@login_required
def team_grant(request):
    """Grant a membership (and approve the user if they were pending).

    Used for both 'approve a pending user' and 'add access to an existing user' —
    the only difference is whether the target was active. Authority is enforced by
    can_grant(); an out-of-scope or over-rank grant is rejected, not silently
    downgraded.
    """
    _require_access(request.user)

    target = get_object_or_404(User, pk=request.POST.get("user"))
    role = request.POST.get("role") or ""
    scope_obj = _resolve_scope(request.POST.get("scope") or "")

    if scope_obj is None or role not in dict(Role.choices):
        messages.error(request, "Pick a valid scope and role.")
        return redirect("dashboards:team")

    if not can_grant(request.user, scope_obj, role):
        raise PermissionDenied("That grant exceeds your authority.")

    # Tenant boundary: the scope belongs to an organization, and a user belongs
    # to exactly one. Never attach a user to another institution's data.
    scope_org_id = organization_of(scope_obj)
    if target.organization_id and scope_org_id and target.organization_id != scope_org_id:
        raise PermissionDenied("That user belongs to a different institution.")

    field = _SCOPE_FIELD[request.POST["scope"].split(":", 1)[0]]
    _, created = UseCaseMembership.objects.get_or_create(
        user=target, role=role, **{field: scope_obj},
        defaults={"granted_by": request.user},
    )

    # Bind the user to this institution on their first grant (approval).
    if scope_org_id and not target.organization_id:
        target.organization_id = scope_org_id

    newly_approved = False
    if not target.is_active:
        target.is_active = True
        target.approved_by = request.user
        target.approved_at = timezone.now()
        target.save(update_fields=[
            "is_active", "approved_by", "approved_at", "organization", "updated_at",
        ])
        newly_approved = True
    elif scope_org_id and target.organization_id == scope_org_id:
        # Already active but org may have just been set above.
        target.save(update_fields=["organization", "updated_at"])

    if newly_approved:
        messages.success(request, f"Approved {target.email} and granted {role} on {scope_obj}.")
    elif created:
        messages.success(request, f"Granted {target.email} {role} on {scope_obj}.")
    else:
        messages.info(request, f"{target.email} already had that access.")
    return redirect("dashboards:team")


@require_POST
@login_required
def team_invite(request):
    """Invite an external collaborator to one of your projects — opt-in, owner-led.

    Cross-institution sharing, but only ever on a single use case (never a region
    or country). The invitee must already be an active user of another
    institution; they keep their home institution and simply gain access to this
    one project until the owner revokes it. The owner alone administers the share
    (their org has authority over the use case, the invitee's does not).
    """
    _require_access(request.user)
    email = (request.POST.get("email") or "").strip().lower()
    role = request.POST.get("role") or ""
    scope_obj = _resolve_scope(request.POST.get("scope") or "")

    if not isinstance(scope_obj, Project):
        messages.error(request, "Collaboration can only be shared on a specific project.")
        return redirect("dashboards:team")
    if role not in dict(Role.choices):
        messages.error(request, "Pick a valid role for the collaborator.")
        return redirect("dashboards:team")
    if not can_grant(request.user, scope_obj, role):
        raise PermissionDenied("That grant exceeds your authority.")

    target = User.objects.filter(email__iexact=email, is_active=True).first()
    if target is None:
        messages.error(
            request, f"No active account found for {email}. They must sign in once first."
        )
        return redirect("dashboards:team")

    _, created = UseCaseMembership.objects.get_or_create(
        user=target, project=scope_obj, role=role,
        defaults={"granted_by": request.user},
    )
    if created:
        messages.success(
            request, f"Invited {target.email} to collaborate on {scope_obj} as {role}."
        )
    else:
        messages.info(request, f"{target.email} already has that access on {scope_obj}.")
    return redirect("dashboards:team")


@require_POST
@login_required
def team_revoke(request):
    """Revoke a membership — only if it falls within the revoker's authority."""
    _require_access(request.user)

    membership = get_object_or_404(UseCaseMembership, pk=request.POST.get("membership"))
    if not manageable_memberships(request.user).filter(pk=membership.pk).exists():
        raise PermissionDenied("That membership is outside your authority.")

    label = f"{membership.user.email} · {membership.role} · {membership.scope}"
    membership.delete()
    messages.success(request, f"Revoked access: {label}.")
    return redirect("dashboards:team")
