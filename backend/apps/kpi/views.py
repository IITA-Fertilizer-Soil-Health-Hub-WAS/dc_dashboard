"""M&E KPI dashboard — Overview + per-project pages (role-scoped)."""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.dashboards.charts import points_map_html
from apps.dashboards.scoping import get_scoped_use_case

from .metrics import (
    PERIODS,
    coverage_metrics,
    enumerator_metrics,
    overview_metrics,
    project_metrics,
    quality_metrics,
)


def _days(request):
    days = request.GET.get("days", "30")
    return days if days in PERIODS else "30"


@login_required
def kpi_overview(request):
    ctx = overview_metrics(request.user, _days(request)) | {"periods": PERIODS}
    return render(request, "kpi/overview.html", ctx)


@login_required
def kpi_project(request, code):
    uc = get_scoped_use_case(request, code)  # 404 if not visible to the user
    ctx = project_metrics(uc, _days(request)) | {"uc": uc, "periods": PERIODS}
    return render(request, "kpi/project.html", ctx)


@login_required
def kpi_quality(request, code):
    uc = get_scoped_use_case(request, code)
    ctx = quality_metrics(uc, _days(request)) | {"uc": uc, "periods": PERIODS}
    return render(request, "kpi/quality.html", ctx)


@login_required
def kpi_enumerators(request, code):
    uc = get_scoped_use_case(request, code)
    m = enumerator_metrics(uc, _days(request))
    ctx = m | {"uc": uc, "periods": PERIODS, "map_html": points_map_html(m["points"])}
    return render(request, "kpi/enumerators.html", ctx)


@login_required
def kpi_coverage(request, code):
    uc = get_scoped_use_case(request, code)
    m = coverage_metrics(uc)
    ctx = m | {"uc": uc, "map_html": points_map_html(m["points"])}
    return render(request, "kpi/coverage.html", ctx)


@login_required
def kpi_export(request, code, kind):
    """Download an M&E export (KPI summary / enumerators CSV, units GeoJSON)."""
    from django.http import Http404

    from .exports import build_export

    uc = get_scoped_use_case(request, code)
    response = build_export(kind, uc)
    if response is None:
        raise Http404("Unknown export type")
    return response


@login_required
def kpi_alerts(request):
    """Recent fired alerts and active rules, scoped to the user's projects."""
    from apps.rbac.permissions import visible_use_cases

    from .models import AlertEvent, AlertRule

    uc_ids = list(visible_use_cases(request.user).values_list("id", flat=True))
    events = list(
        AlertEvent.objects.filter(use_case_id__in=uc_ids)
        .select_related("rule", "use_case")[:100]
    )
    rules = (
        AlertRule.objects.filter(use_case_id__in=uc_ids, is_enabled=True)
        .select_related("use_case")
    )
    return render(request, "kpi/alerts.html", {
        "events": events,
        "active_rules": rules.count(),
    })
