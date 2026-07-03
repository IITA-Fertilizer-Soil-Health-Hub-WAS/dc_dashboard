"""Per-row actions for console models — ports the admin-only actions into the
in-app console so nothing is lost when those models leave the Django admin.

Each action's ``fn(request, obj)`` returns either a status string (flashed as a
message) or an HttpResponse (e.g. a file download).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from django.http import HttpResponse


@dataclass(frozen=True)
class Action:
    slug: str
    label: str
    fn: Callable
    style: str = "btn-request"  # button class from base.html
    # When set, the button is only shown for rows where ``applies(obj)`` is
    # true — e.g. hide Approve once a user is already active. ``None`` = always.
    applies: Callable | None = None


# ---- Project actions ----
def uc_validate(request, uc):
    from apps.config_admin.loader import export_config, validate_config

    problems = validate_config(export_config(uc))
    if problems:
        return f"{uc.code}: " + "; ".join(problems)
    return f"{uc.code}: configuration OK."


def uc_sync(request, uc):
    from apps.ingestion.sync import sync_project
    from apps.validation.engine import run_for_project

    stats = sync_project(uc)
    vstats = run_for_project(uc)
    return f"{uc.code}: synced (+{stats.created} new), {vstats.opened} flags opened."


def uc_export(request, uc):
    from apps.config_admin.loader import dump_yaml

    resp = HttpResponse(dump_yaml(uc), content_type="application/x-yaml")
    resp["Content-Disposition"] = f'attachment; filename="{uc.code.lower()}.yaml"'
    return resp


# ---- User actions (were UserAdmin actions) ----
def user_approve(request, user):
    from apps.accounts.models import UserProfile

    if user.is_approved:
        return f"{user.email} is already approved."
    # Approval is a review of the profile the user submitted — refuse if there's
    # nothing to review yet.
    if not UserProfile.objects.filter(user=user, completed_at__isnull=False).exists():
        return f"{user.email} hasn't submitted their profile yet — can't approve."
    user.approve(by=request.user)
    return f"Approved {user.email}."


def user_deactivate(request, user):
    user.is_active = False
    user.save(update_fields=["is_active", "updated_at"])
    return f"Deactivated {user.email}."


PROJECT_ACTIONS = (
    Action("sync", "Sync now", uc_sync, "btn-open"),
    Action("validate", "Validate", uc_validate),
    Action("export", "Export YAML", uc_export),
)

USER_ACTIONS = (
    Action("approve", "Approve", user_approve, "btn-approve",
           applies=lambda u: not u.is_approved),
    Action("deactivate", "Deactivate", user_deactivate, "btn-decline",
           applies=lambda u: u.is_active),
)
