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
    from apps.review.models import ReviewState
    from apps.submissions.models import Enumerator, Submission

    scope = f"?project={uc.code}"
    subs = Submission.objects.filter(project=uc)
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
         "done": subs.exists(),
         "url": reverse("dashboards:project", args=[uc.code]) + "?tab=data",
         "hint": "Pull data from the collection server."},
        {"label": "Review & endorse a submission (Gate 1)",
         "done": subs.filter(review__state__in=[ReviewState.QC_PENDING,
                                                ReviewState.APPROVED]).exists(),
         "url": reverse("dashboards:project", args=[uc.code]) + "?tab=review",
         "hint": "Check it, fix any issues, then endorse."},
        {"label": "Validate a record (Gate 2)",
         "done": subs.filter(review__state=ReviewState.APPROVED).exists(),
         "url": reverse("dashboards:qc_signoff", args=[uc.code]),
         "hint": "Final sign-off — it joins the clean dataset."},
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


def _enumerator_checklist(user) -> dict:
    from django.db.models import Q

    from apps.accounts.models import UserProfile
    from apps.fieldwork.models import UnitAssignment
    from apps.review.corrections import open_corrections
    from apps.submissions.models import Submission

    profile_done = UserProfile.objects.filter(user=user, completed_at__isnull=False).exists()
    has_assign = UnitAssignment.objects.filter(enumerator=user).exists()
    has_subs = Submission.objects.filter(
        Q(collected_by=user) | Q(enumerator__user=user)).exists()
    open_fix = open_corrections(user).count()
    items = [
        {"label": "Complete your profile", "done": profile_done,
         "url": reverse("profile"),
         "hint": "Register your details once — never re-enter them in the field."},
        {"label": "Find your assignments", "done": has_assign,
         "url": reverse("dashboards:my_assignments"),
         "hint": "What you've been asked to collect."},
        {"label": "See your submissions", "done": has_subs,
         "url": reverse("dashboards:my_submissions"),
         "hint": "They appear here after each sync."},
        {"label": f"Fix flagged issues{f' ({open_fix})' if open_fix else ''}",
         "done": open_fix == 0,
         "url": reverse("dashboards:my_submissions"),
         "hint": "Correct in ODK Collect and resend." if open_fix
                 else "Nothing to fix right now."},
    ]
    return _pack("Your work", items)


def _is_enumerator(user) -> bool:
    from apps.fieldwork.models import UnitAssignment
    from apps.rbac.models import Membership, Role

    return bool(
        Membership.objects.filter(user=user, role=Role.ENUMERATOR).exists()
        or UnitAssignment.objects.filter(enumerator=user).exists()
    )


def getting_started(user, active_uc):
    """The checklist for this user in this context, or None if not applicable."""
    from apps.rbac.permissions import can_manage_access

    if active_uc is not None and can_manage_access(user):
        return _project_checklist(active_uc)
    if getattr(user, "is_staff", False) and active_uc is None:
        return _admin_checklist()
    if _is_enumerator(user):
        return _enumerator_checklist(user)
    return None
