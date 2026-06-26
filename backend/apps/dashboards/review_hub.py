"""Review hub — the platform's primary review surface.

Review is a first-class feature, not something buried inside each project. This
page aggregates every submission awaiting the signed-in user's action across all
their projects, split by gate:

  * Validate (Gate 2) — QC_PENDING in projects where they give final validation,
  * Endorse  (Gate 1) — actionable submissions in projects where they endorse,
  * Assigned — submissions explicitly assigned to them.

Capability is resolved as use-case id sets in a few set-based queries (mirroring
rbac.user_can, including the Country fallback), so the page stays cheap even with
many projects — no per-submission permission checks.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.rbac.models import Role, UseCaseMembership
from apps.rbac.permissions import visible_use_cases
from apps.review.models import ReviewState
from apps.submissions.models import Submission
from apps.usecases.models import UseCase

GATE1_ROLES = [Role.TRIAL_COORDINATOR, Role.COUNTRY_COORDINATOR]
COORDINATOR_ROLES = [
    Role.TRIAL_COORDINATOR, Role.COUNTRY_COORDINATOR, Role.REGIONAL_COORDINATOR,
]
GATE1_STATES = [
    ReviewState.INGESTED, ReviewState.FLAGGED, ReviewState.IN_REVIEW,
    ReviewState.EDIT_REQUESTED, ReviewState.EDITED,
]


def _ucs_with_roles(user, roles):
    """Active use case ids where the user holds one of `roles` (any scope level)."""
    return UseCase.objects.filter(
        Q(memberships__user=user, memberships__role__in=roles)
        | Q(country__memberships__user=user, country__memberships__role__in=roles)
        | Q(country__region__memberships__user=user, country__region__memberships__role__in=roles),
        is_active=True,
    ).values_list("id", flat=True).distinct()


def _ucs_with_any_regional():
    """Active use case ids covered by any active Regional Coordinator."""
    r = Role.REGIONAL_COORDINATOR
    return UseCase.objects.filter(
        Q(memberships__role=r, memberships__user__is_active=True)
        | Q(country__memberships__role=r, country__memberships__user__is_active=True)
        | Q(country__region__memberships__role=r, country__region__memberships__user__is_active=True),
    ).values_list("id", flat=True).distinct()


def review_capability(user):
    """(gate1_uc_ids, gate2_uc_ids) the user may act on — matches user_can."""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return set(), set()
    if getattr(user, "is_platform_admin", False):
        all_ids = set(UseCase.objects.filter(is_active=True).values_list("id", flat=True))
        return all_ids, all_ids
    if not UseCaseMembership.objects.filter(user=user, role__in=COORDINATOR_ROLES).exists():
        return set(), set()
    g1 = set(_ucs_with_roles(user, GATE1_ROLES))
    regional = set(_ucs_with_roles(user, [Role.REGIONAL_COORDINATOR]))
    country = set(_ucs_with_roles(user, [Role.COUNTRY_COORDINATOR]))
    # Gate 2: Regional always; a Country Coordinator only where no Regional covers.
    g2 = regional | (country - set(_ucs_with_any_regional()))
    return g1, g2


def review_todo_count(user) -> int:
    """How many submissions await this user's gate action — for the nav badge."""
    g1, g2 = review_capability(user)
    if not g1 and not g2:
        return 0
    n = 0
    if g2:
        n += Submission.objects.filter(
            use_case_id__in=list(g2), review__state=ReviewState.QC_PENDING
        ).count()
    if g1:
        n += Submission.objects.filter(
            use_case_id__in=list(g1), review__state__in=GATE1_STATES
        ).count()
    return n


@login_required
def review_hub(request):
    user = request.user
    g1, g2 = review_capability(user)
    sel = ("use_case", "enumerator", "household", "review", "review__endorsed_by")

    to_validate = list(
        Submission.objects.filter(use_case_id__in=list(g2), review__state=ReviewState.QC_PENDING)
        .select_related(*sel).order_by("-updated_at")[:200]
    ) if g2 else []
    to_endorse = list(
        Submission.objects.filter(use_case_id__in=list(g1), review__state__in=GATE1_STATES)
        .select_related(*sel).order_by("review__state", "-ingested_at")[:200]
    ) if g1 else []
    assigned = list(
        Submission.objects.filter(
            use_case__in=visible_use_cases(user), review__assigned_to=user
        )
        .exclude(review__state__in=[ReviewState.APPROVED, ReviewState.DECLINED])
        .select_related(*sel).order_by("review__state", "-updated_at")[:100]
    )
    return render(request, "dashboards/review_hub.html", {
        "to_validate": to_validate,
        "to_endorse": to_endorse,
        "assigned": assigned,
    })


_HUB_ACTIONS = {"ENDORSE", "QC_APPROVE", "DECLINE"}


@require_POST
@login_required
def review_hub_action(request):
    """Perform a quick review action from the hub, then return to it."""
    from apps.review import services
    from apps.review.state_machine import ReviewPermissionDenied, TransitionError

    sub = get_object_or_404(Submission, pk=request.POST.get("submission"))
    if not visible_use_cases(request.user).filter(pk=sub.use_case_id).exists():
        raise PermissionDenied("That submission is outside your projects.")

    action = request.POST.get("action")
    fn = {
        "ENDORSE": services.endorse,
        "QC_APPROVE": services.qc_approve,
        "DECLINE": services.decline,
    }.get(action)
    if fn is None:
        messages.error(request, "Unknown action.")
        return redirect("dashboards:review_hub")

    try:
        fn(request.user, sub, note=(request.POST.get("note") or "").strip())
        verb = {"ENDORSE": "Endorsed", "QC_APPROVE": "Validated", "DECLINE": "Declined"}[action]
        messages.success(request, f"{verb} {sub.ona_uuid[:12]} ({sub.use_case.code}).")
    except (ReviewPermissionDenied, TransitionError) as exc:
        messages.error(request, str(exc))
    return redirect("dashboards:review_hub")
