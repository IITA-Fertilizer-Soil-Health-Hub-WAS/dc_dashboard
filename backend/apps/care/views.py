"""Health service delivery — Phase 1 views: programmes, client register, timeline.

Everything is scoped to the projects a user may see; the data is the existing
CollectionUnits (clients) and Submissions (encounters), viewed through a
care lens.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.fieldwork.models import CollectionUnit
from apps.rbac.permissions import can_manage_access, visible_projects
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
    units = list(units.annotate(
        visits=Count("submissions", distinct=True),
        last_visit=Max("submissions__event_date"),
    ).order_by("code")[:500])

    # Current worker per unit (active assignment) so the register shows caseload.
    from .models import CareAssignment

    worker_by_unit = {
        a.unit_id: a.worker for a in CareAssignment.objects.filter(
            unit__in=units, is_active=True).select_related("worker")
    }
    for u in units:
        u.worker = worker_by_unit.get(u.id)

    from apps.accounts.models import User

    can_assign = request.user.is_staff or can_manage_access(request.user)
    workers = User.objects.filter(
        organization=program.project.organization_id, is_active=True
    ).order_by("full_name", "email") if program.project.organization_id else User.objects.none()
    return render(request, "care/clients.html", {
        "program": program, "units": units, "q": q,
        "workers": workers, "can_assign": can_assign,
    })


@login_required
@require_POST
def assign(request, code):
    program = get_object_or_404(_visible_programs(request.user), project__code=code)
    unit = get_object_or_404(CollectionUnit, pk=request.POST.get("unit"), project=program.project)
    from apps.accounts.models import User

    from .services import assign_client

    worker = User.objects.filter(pk=request.POST.get("worker")).first()
    if worker is not None:
        assign_client(program, unit, worker, by=request.user,
                      note=(request.POST.get("note") or "").strip())
    return redirect(f"{reverse('care:clients', args=[code])}?q={request.GET.get('q', '')}")


@login_required
def my_caseload(request):
    from .plan import client_visit_plan, plan_summary
    from .services import worker_caseload

    rows = []
    for a in worker_caseload(request.user):
        encounters = list(Submission.objects.filter(collection_unit=a.unit).select_related("crop"))
        plan = client_visit_plan(a.unit, list(a.program.project.schedule.all()), encounters)
        summary = plan_summary(plan)
        next_due = next((v for v in plan if v["is_open"]), None)
        rows.append({"a": a, "summary": summary, "next_due": next_due,
                     "open": [v for v in plan if v["is_open"]]})
    # Overdue caseload first.
    rows.sort(key=lambda r: (-r["summary"]["overdue"], -r["summary"]["due"], r["a"].unit.code))
    return render(request, "care/my_caseload.html", {"rows": rows})


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
    from .plan import program_coverage, worker_breakdown

    program = get_object_or_404(_visible_programs(request.user), project__code=code)
    return render(request, "care/coverage.html", {
        "program": program, "cov": program_coverage(program),
        "workers": worker_breakdown(program),
    })


@login_required
def report_csv(request, code):
    import csv

    from django.http import HttpResponse

    from .plan import program_status_rows

    program = get_object_or_404(_visible_programs(request.user), project__code=code)
    rows = program_status_rows(program)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{code.lower()}_care_status.csv"'
    writer = csv.writer(response)
    writer.writerow([program.client_label + " ID", "Name", "Worker", "Visits done",
                     "Visits expected", "Overdue", "Last visit"])
    for r in rows:
        writer.writerow([r["code"], r["name"], r["worker"], r["done"], r["expected"],
                         r["overdue"], r["last_visit"]])
    return response
