"""Projects directory — scalable browse + self-service access requests.

Replaces the dump-every-project landing page. A user sees their own projects by
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

from apps.projects.models import Country, Organization, Project
from apps.rbac.models import ProjectAccessRequest
from apps.rbac.permissions import can_manage_access, visible_projects

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
        from apps.review.models import REVIEW_CLOSED_STATES
        from apps.submissions.models import Submission
        from apps.validation.models import ValidationFlag

        ids = list(member_ids)
        out["awaiting_review"] = (
            Submission.objects.filter(project_id__in=ids)
            .exclude(review__state__in=REVIEW_CLOSED_STATES).count()
        )
        out["open_issues"] = ValidationFlag.objects.filter(
            rule__project_id__in=ids, status=ValidationFlag.Status.OPEN
        ).count()
    return out


def _catalogue():
    """The public discovery catalogue: every active project across all
    institutions. Only names/metadata are exposed here — data stays private
    until access is granted (see visible_projects for the data gate)."""
    return Project.objects.filter(is_active=True).select_related("country", "organization")


@login_required
def projects(request):
    """Directory of projects. Two scopes:

    * ``all`` (default) — the global catalogue: every institution's projects,
      each with Info + Request-access, filterable by institution/keyword/country.
      A card is inert (greyed) when its owner hasn't opened access requests.
    * ``mine`` — just the projects you belong to.

    Project = workspace: on the bare landing, a user with exactly one project is
    taken straight into it. Opening the directory clears any active workspace.
    """
    user = request.user
    is_index = bool(request.resolver_match and request.resolver_match.url_name == "index")
    if is_index and not request.GET.get("scope") and not request.GET.get("q"):
        mine = visible_projects(user)
        if mine.count() == 1:
            return redirect("dashboards:project", code=mine.first().code)
    request.session.pop("active_project", None)  # browsing the directory = leave the workspace

    scope = "mine" if request.GET.get("scope") == "mine" else "all"
    q = (request.GET.get("q") or "").strip()
    country = (request.GET.get("country") or "").strip()
    org = (request.GET.get("org") or "").strip()

    member_ids = set(visible_projects(user).values_list("id", flat=True))

    # 'mine' = projects you belong to; 'all' = the global catalogue you can
    # discover and request access in.
    if scope == "mine":
        base = visible_projects(user).select_related("country", "organization")
    else:
        base = _catalogue()
    if q:
        base = base.filter(
            Q(code__icontains=q) | Q(name__icontains=q) | Q(description__icontains=q)
        )
    if org:
        base = base.filter(organization__code=org)
    if country:
        base = base.filter(country__code=country)
    base = base.order_by("name")

    page = Paginator(base, PAGE_SIZE).get_page(request.GET.get("page"))
    pending_ids = set(
        ProjectAccessRequest.objects.filter(
            user=user, status=ProjectAccessRequest.Status.PENDING
        ).values_list("project_id", flat=True)
    )
    rows = [
        {
            "uc": uc,
            "is_member": uc.id in member_ids,
            "pending": uc.id in pending_ids,
            # Owner opened this project to outside requests — drives the buttons.
            "open": uc.allow_access_requests,
        }
        for uc in page
    ]
    # Filter options span the whole catalogue (global discovery).
    orgs = Organization.objects.filter(
        projects__is_active=True
    ).distinct().order_by("name")
    countries = Country.objects.filter(
        projects__is_active=True
    ).distinct().order_by("name")

    # Personal 'attention' strip only on the your-projects landing.
    is_landing = scope == "mine" and not q and not country and not org
    home = _home_summary(user, member_ids) if is_landing else {}

    return render(request, "dashboards/projects.html", {
        "rows": rows, "page": page, "scope": scope, "q": q,
        "country": country, "countries": countries, "org": org, "orgs": orgs,
        "mine_count": len(member_ids), "home": home, "is_landing": is_landing,
    })


@require_http_methods(["GET", "POST"])
@login_required
def project_request(request, code):
    """Request access to a project: describe what you intend to do; a coordinator
    reads that and grants the fitting role."""
    user = request.user
    uc = get_object_or_404(Project, code=code, is_active=True)

    if visible_projects(user).filter(pk=uc.pk).exists():
        messages.info(request, f"You already have access to {uc.code}.")
        return redirect("dashboards:projects")

    # The owner/institution must have opened this project to outside requests.
    # (Discovery is global, but a closed project is inert — see the catalogue.)
    if not uc.allow_access_requests:
        raise PermissionDenied("This project is not accepting access requests.")

    existing = ProjectAccessRequest.objects.filter(
        user=user, project=uc, status=ProjectAccessRequest.Status.PENDING
    ).first()

    if request.method == "POST":
        note = (request.POST.get("note") or "").strip()
        if not note:
            return render(request, "dashboards/project_request.html", {
                "uc": uc, "existing": existing, "note": note,
                "error": "Please describe what you intend to do on this project.",
            })
        ProjectAccessRequest.objects.update_or_create(
            user=user, project=uc, status=ProjectAccessRequest.Status.PENDING,
            defaults={"note": note},
        )
        messages.success(request, f"Access requested for {uc.code}. A coordinator will review it.")
        return redirect("dashboards:projects")

    return render(request, "dashboards/project_request.html", {
        "uc": uc, "existing": existing, "note": existing.note if existing else "",
    })
