"""A progress-aware 'getting started' checklist for the current role/context.

Unlike a one-shot tour, this reads the real data state and shows what's left to
do, linking straight to each action. Returns None when there's nothing to guide.
"""
from __future__ import annotations

from django.urls import reverse


def _pack(title: str, items: list[dict]) -> dict:
    done = sum(1 for i in items if i["done"])
    return {
        "id": title.lower().replace(" ", "-"),
        "title": title, "items": items,
        "done": done, "total": len(items), "complete": done == len(items),
    }


def _project_checklist(uc) -> dict:
    from apps.submissions.models import Enumerator, Submission

    scope = f"?project={uc.code}"
    items = [
        {"label": "Import form fields from the server",
         "done": uc.forms.exclude(field_schema=[]).exists(),
         "url": reverse("console:setup") + scope,
         "hint": "So rules & reconciliation know your fields."},
        {"label": "Add a validation rule",
         "done": uc.rules.exists(),
         "url": reverse("console:rule_new") + scope,
         "hint": "Catch bad data automatically."},
        {"label": "Register enumerators",
         "done": Enumerator.objects.filter(project=uc).exists(),
         "url": reverse("console:list", args=["enumerators"]) + scope,
         "hint": "Who collects the data."},
        {"label": "Sync your first submissions",
         "done": Submission.objects.filter(project=uc).exists(),
         "url": reverse("dashboards:project", args=[uc.code]) + "?tab=data",
         "hint": "Pull data from the collection server."},
    ]
    return _pack("Getting started", items)


def _admin_checklist() -> dict:
    from apps.projects.models import Country, Organization, Project, Region
    from apps.rbac.models import Membership, Role

    coord_roles = [Role.TRIAL_COORDINATOR, Role.COUNTRY_COORDINATOR, Role.REGIONAL_COORDINATOR]
    items = [
        {"label": "Create an institution",
         "done": Organization.objects.exists(),
         "url": reverse("console:admin_setup"),
         "hint": "The tenant that owns projects & data."},
        {"label": "Add geography (region & country)",
         "done": Region.objects.exists() and Country.objects.exists(),
         "url": reverse("console:admin_setup"),
         "hint": "Drives the coordinator hierarchy."},
        {"label": "Onboard the first project",
         "done": Project.objects.exists(),
         "url": reverse("console:onboard"),
         "hint": "Connect a collection server."},
        {"label": "Invite a coordinator",
         "done": Membership.objects.filter(role__in=coord_roles).exists(),
         "url": reverse("console:list", args=["memberships"]),
         "hint": "Delegate project management."},
    ]
    return _pack("Set up the platform", items)


def getting_started(user, active_uc):
    """The checklist for this user in this context, or None if not applicable."""
    from apps.rbac.permissions import can_manage_access

    if active_uc is not None and can_manage_access(user):
        return _project_checklist(active_uc)
    if getattr(user, "is_staff", False) and active_uc is None:
        return _admin_checklist()
    return None
