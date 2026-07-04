"""Health service delivery — Phase 1 views: programmes, client register, timeline.

Everything is scoped to the projects a user may see; the data is the existing
CollectionUnits (clients) and Submissions (encounters), viewed through a
care lens.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, render

from apps.fieldwork.models import CollectionUnit
from apps.rbac.permissions import visible_projects
from apps.submissions.models import Submission

from .models import CareProgram


def _visible_programs(user):
    return (CareProgram.objects.filter(project__in=visible_projects(user), is_active=True)
            .select_related("project"))


@login_required
def programs(request):
    progs = _visible_programs(request.user).annotate(
        clients=Count("project__collection_units", distinct=True))
    return render(request, "care/programs.html", {"programs": progs})


@login_required
def clients(request, code):
    program = get_object_or_404(_visible_programs(request.user), project__code=code)
    q = (request.GET.get("q") or "").strip()
    units = CollectionUnit.objects.filter(project=program.project)
    if q:
        units = units.filter(Q(code__icontains=q) | Q(name__icontains=q))
    units = units.annotate(
        visits=Count("submissions", distinct=True),
        last_visit=Max("submissions__event_date"),
    ).order_by("code")[:500]
    return render(request, "care/clients.html", {"program": program, "units": units, "q": q})


@login_required
def client_timeline(request, code, unit_id):
    from .plan import client_visit_plan, plan_summary

    program = get_object_or_404(_visible_programs(request.user), project__code=code)
    unit = get_object_or_404(CollectionUnit, pk=unit_id, project=program.project)
    encounters = list(
        Submission.objects.filter(collection_unit=unit)
        .select_related("enumerator", "form", "review", "crop")
        .order_by("-event_date", "-ingested_at")[:200]
    )
    schedule = list(program.project.schedule.all())
    plan = client_visit_plan(unit, schedule, encounters)
    return render(request, "care/client_timeline.html", {
        "program": program, "unit": unit, "encounters": encounters,
        "plan": plan, "plan_summary": plan_summary(plan),
    })


@login_required
def coverage(request, code):
    from .plan import program_coverage

    program = get_object_or_404(_visible_programs(request.user), project__code=code)
    return render(request, "care/coverage.html",
                  {"program": program, "cov": program_coverage(program)})
