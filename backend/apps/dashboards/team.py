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
from apps.rbac.models import Role, UseCaseMembership
from apps.rbac.permissions import (
    can_grant,
    can_manage_access,
    grantable_roles,
    grantable_scopes,
    manageable_memberships,
    pending_users,
)

# Maps the scope <select> token prefix to the membership FK field.
_SCOPE_FIELD = {"region": "region", "country": "country", "usecase": "use_case"}


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
    for uc in scopes["use_cases"]:
        opts.append({"value": f"usecase:{uc.pk}", "label": f"Use case · {uc.code}"})
    return opts


def _role_options(user) -> list[dict]:
    labels = dict(Role.choices)
    return [{"value": r, "label": labels[r]} for r in grantable_roles(user)]


def _resolve_scope(token: str):
    """Parse a 'level:pk' token into a scope object, or None if invalid."""
    level, _, pk = (token or "").partition(":")
    if level not in _SCOPE_FIELD:
        return None
    from apps.usecases.models import Country, Region, UseCase

    model = {"region": Region, "country": Country, "usecase": UseCase}[level]
    return model.objects.filter(pk=pk).first()


@login_required
def team(request):
    """The Team & Access dashboard: pending approvals + the access you administer."""
    _require_access(request.user)
    memberships = manageable_memberships(request.user).order_by(
        "user__email", "role"
    )
    ctx = {
        "pending": pending_users(),
        "memberships": memberships,
        "scope_options": _scope_options(request.user),
        "role_options": _role_options(request.user),
        "active_users": User.objects.filter(is_active=True).order_by("email"),
    }
    return render(request, "dashboards/team.html", ctx)


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

    field = _SCOPE_FIELD[request.POST["scope"].split(":", 1)[0]]
    _, created = UseCaseMembership.objects.get_or_create(
        user=target, role=role, **{field: scope_obj},
        defaults={"granted_by": request.user},
    )

    newly_approved = False
    if not target.is_active:
        target.is_active = True
        target.approved_by = request.user
        target.approved_at = timezone.now()
        target.save(update_fields=["is_active", "approved_by", "approved_at", "updated_at"])
        newly_approved = True

    if newly_approved:
        messages.success(request, f"Approved {target.email} and granted {role} on {scope_obj}.")
    elif created:
        messages.success(request, f"Granted {target.email} {role} on {scope_obj}.")
    else:
        messages.info(request, f"{target.email} already had that access.")
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
