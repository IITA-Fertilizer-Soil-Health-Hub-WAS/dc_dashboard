"""Projects directory — scalable browse + self-service access requests.

Replaces the dump-every-use-case landing page. A user sees their own projects by
default, can search/filter across all projects in their institution, and request
access to ones they are not yet a member of. Built to stay usable at thousands of
projects: one paginated, indexed query — never a per-project fan-out.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.rbac.models import UseCaseAccessRequest
from apps.rbac.permissions import can_manage_access, visible_use_cases
from apps.usecases.models import Country, UseCase

PAGE_SIZE = 24


def _home_summary(user, member_ids):
    """Role-aware 'needs your attention' figures for the landing page: collection
    progress for enumerators, the review/issue backlog for coordinators."""
    from apps.fieldwork.models import UnitAssignment

    out = {}
    units = UnitAssignment.objects.filter(enumerator=user)
    total = units.count()
    if total:
        collected = units.filter(unit__submissions__isnull=False).distinct().count()
        pct = round(collected / total * 100) if total else 0
        out["assignments"] = {"total": total, "collected": collected,
                              "pending": total - collected, "pct": pct}
    if can_manage_access(user) and member_ids:
        from apps.review.models import ReviewState
        from apps.submissions.models import Submission
        from apps.validation.models import ValidationFlag

        ids = list(member_ids)
        out["awaiting_review"] = (
            Submission.objects.filter(use_case_id__in=ids)
            .exclude(review__state__in=[ReviewState.APPROVED, ReviewState.DECLINED]).count()
        )
        out["open_issues"] = ValidationFlag.objects.filter(
            rule__use_case_id__in=ids, status=ValidationFlag.Status.OPEN
        ).count()
    return out


def _org_use_cases(user):
    """Active use cases the user may see in the directory: their institution's
    (a hub operator sees all; a user with no institution yet sees none)."""
    qs = UseCase.objects.filter(is_active=True).select_related("country", "organization")
    if getattr(user, "is_platform_admin", False):
        return qs
    if user.organization_id:
        return qs.filter(organization_id=user.organization_id)
    return qs.none()


@login_required
def projects(request):
    """Directory of projects: 'mine' (default) or 'all' in my institution."""
    user = request.user
    scope = "all" if request.GET.get("scope") == "all" else "mine"
    q = (request.GET.get("q") or "").strip()
    country = (request.GET.get("country") or "").strip()

    member_ids = set(visible_use_cases(user).values_list("id", flat=True))
    org_qs = _org_use_cases(user)

    # 'mine' = projects you belong to (membership is the authorization, no org
    # gate needed); 'all' = the institution directory you may request access in.
    if scope == "all":
        base = org_qs
    else:
        base = visible_use_cases(user).select_related("country", "organization")
    if q:
        base = base.filter(Q(code__icontains=q) | Q(name__icontains=q))
    if country:
        base = base.filter(country__code=country)
    base = base.order_by("code")

    page = Paginator(base, PAGE_SIZE).get_page(request.GET.get("page"))
    pending_ids = set(
        UseCaseAccessRequest.objects.filter(
            user=user, status=UseCaseAccessRequest.Status.PENDING
        ).values_list("use_case_id", flat=True)
    )
    rows = [
        {"uc": uc, "is_member": uc.id in member_ids, "pending": uc.id in pending_ids}
        for uc in page
    ]
    countries = Country.objects.filter(
        use_cases__in=org_qs
    ).distinct().order_by("name")

    # Personal 'attention' strip only on the default (your-projects) landing —
    # not when browsing/searching the wider directory.
    is_landing = scope == "mine" and not q and not country
    home = _home_summary(user, member_ids) if is_landing else {}

    return render(request, "dashboards/projects.html", {
        "rows": rows, "page": page, "scope": scope, "q": q,
        "country": country, "countries": countries,
        "mine_count": len(member_ids), "home": home, "is_landing": is_landing,
    })


@login_required
def project_nav_search(request):
    """Type-ahead for the sidebar Projects dropdown — the user's matching projects."""
    q = (request.GET.get("q") or "").strip()
    qs = visible_use_cases(request.user)
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(name__icontains=q))
    projects = list(qs.order_by("code")[:12])
    return render(request, "dashboards/_nav_projects.html", {"projects": projects})


@require_http_methods(["GET", "POST"])
@login_required
def project_request(request, code):
    """Request access to a project: describe what you intend to do; a coordinator
    reads that and grants the fitting role."""
    user = request.user
    uc = get_object_or_404(UseCase, code=code, is_active=True)

    # Tenant guard: you can only request projects in your own institution.
    if not getattr(user, "is_platform_admin", False):
        if not user.organization_id or uc.organization_id != user.organization_id:
            raise PermissionDenied("That project is in another institution.")

    if visible_use_cases(user).filter(pk=uc.pk).exists():
        messages.info(request, f"You already have access to {uc.code}.")
        return redirect("dashboards:projects")

    existing = UseCaseAccessRequest.objects.filter(
        user=user, use_case=uc, status=UseCaseAccessRequest.Status.PENDING
    ).first()

    if request.method == "POST":
        note = (request.POST.get("note") or "").strip()
        if not note:
            return render(request, "dashboards/project_request.html", {
                "uc": uc, "existing": existing, "note": note,
                "error": "Please describe what you intend to do on this project.",
            })
        UseCaseAccessRequest.objects.update_or_create(
            user=user, use_case=uc, status=UseCaseAccessRequest.Status.PENDING,
            defaults={"note": note},
        )
        messages.success(request, f"Access requested for {uc.code}. A coordinator will review it.")
        return redirect("dashboards:projects")

    return render(request, "dashboards/project_request.html", {
        "uc": uc, "existing": existing, "note": existing.note if existing else "",
    })
