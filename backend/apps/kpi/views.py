"""M&E KPI dashboard — Overview + per-project pages (role-scoped)."""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.dashboards.charts import points_map_html
from apps.dashboards.scoping import get_scoped_project

from .metrics import (
    PERIODS,
    coverage_metrics,
    enumerator_metrics,
    enumerator_trend,
    overview_metrics,
    project_metrics,
    project_quality_trend,
    quality_metrics,
)


def _days(request):
    days = request.GET.get("days", "30")
    return days if days in PERIODS else "30"


def _scoped(request, code):
    """Scope to a project AND make it the active workspace, so the Monitor pages
    render inside the project rail (the KPI pages are now workspace sections, not
    a separate area with their own tab bar)."""
    uc = get_scoped_project(request, code)  # 404 if not visible to the user
    request.session["active_project"] = uc.code
    return uc


@login_required
def kpi_overview(request):
    ctx = overview_metrics(request.user, _days(request)) | {"periods": PERIODS}
    return render(request, "kpi/overview.html", ctx)


@login_required
def kpi_project(request, code):
    uc = _scoped(request, code)
    from .exports import export_options

    ctx = project_metrics(uc, _days(request)) | {
        "uc": uc, "periods": PERIODS, "exports": export_options(),
    }
    return render(request, "kpi/project.html", ctx)


@login_required
def kpi_quality(request, code):
    uc = _scoped(request, code)
    ctx = quality_metrics(uc, _days(request)) | {
        "uc": uc, "periods": PERIODS, "qtrend": project_quality_trend(uc),
    }
    return render(request, "kpi/quality.html", ctx)


@login_required
def kpi_enumerators(request, code):
    uc = _scoped(request, code)
    m = enumerator_metrics(uc, _days(request))
    ctx = m | {"uc": uc, "periods": PERIODS, "map_html": points_map_html(m["points"])}
    return render(request, "kpi/enumerators.html", ctx)


@login_required
def kpi_enumerator_detail(request, code, enum_id):
    """One enumerator's scorecard row + their flag-rate-over-time trend, so a
    coordinator can spot degrading quality early (not just a period average)."""
    from django.http import Http404

    uc = _scoped(request, code)
    m = enumerator_metrics(uc, _days(request))
    row = next((r for r in m["leaderboard"] if str(r["enumerator_id"]) == str(enum_id)), None)
    trend = enumerator_trend(uc, enum_id)
    if row is None and trend["enumerator"] is None:
        raise Http404("No such enumerator on this project.")
    return render(request, "kpi/enumerator_detail.html", {
        "uc": uc, "row": row, "trend": trend, "days": _days(request), "periods": PERIODS,
    })


@login_required
def kpi_coverage(request, code):
    uc = _scoped(request, code)
    m = coverage_metrics(uc)
    ctx = m | {"uc": uc, "map_html": points_map_html(m["points"])}
    return render(request, "kpi/coverage.html", ctx)


@login_required
def kpi_export(request, code, kind):
    """Download an M&E export. `units-geojson` is the spatial layer; the other
    kinds are tabular datasets serialised in ?fmt= (csv default, xlsx/dta/sav)."""
    from django.http import Http404

    from .exports import render_dataset, units_geojson

    uc = get_scoped_project(request, code)
    if kind == "units-geojson":
        return units_geojson(uc)
    fmt = request.GET.get("fmt", "csv")
    response = render_dataset(kind, fmt, uc, _days(request))
    if response is None:
        raise Http404("Unknown export type")
    return response


@login_required
def kpi_alerts(request):
    """Recent fired alerts and active rules, scoped to the user's projects."""
    from apps.rbac.permissions import visible_projects

    from .models import AlertEvent, AlertRule

    uc_ids = list(visible_projects(request.user).values_list("id", flat=True))
    events = list(
        AlertEvent.objects.filter(project_id__in=uc_ids)
        .select_related("rule", "project")[:100]
    )
    rules = (
        AlertRule.objects.filter(project_id__in=uc_ids, is_enabled=True)
        .select_related("project")
    )
    from .alerts import METRICS

    return render(request, "kpi/alerts.html", {
        "events": events,
        "active_rules": rules.count(),
        "supported_metrics": METRICS,
    })


# ---------------------------------------------------------------------------
# Self-serve dashboard builder — users assemble metric widgets into a saved,
# optionally-shared dashboard (closes the "flexible analytics" gap).
# ---------------------------------------------------------------------------
def _visible_dashboards(user):
    """The dashboards a user may open: their own, plus institution-shared ones."""
    from django.db.models import Q

    from .models import Dashboard

    scope = Q(owner=user)
    if getattr(user, "organization_id", None):
        scope |= Q(shared=True, owner__organization_id=user.organization_id)
    elif getattr(user, "is_superuser", False):
        scope |= Q(shared=True)
    return Dashboard.objects.filter(scope).select_related("owner", "project").distinct()


def _dashboard_scope_ids(user, dashboard):
    """Project ids a dashboard's metrics run over — the viewer's visible projects,
    narrowed to the dashboard's project when it pins one."""
    from apps.rbac.permissions import visible_projects

    ids = set(visible_projects(user).values_list("id", flat=True))
    if dashboard.project_id:
        return ids & {dashboard.project_id}
    return ids


@login_required
def dashboards(request):
    return render(request, "kpi/dashboards.html",
                  {"dashboards": _visible_dashboards(request.user).order_by("name")})


@login_required
def dashboard_view(request, pk):
    from django.shortcuts import get_object_or_404

    from .builder import compute_widget

    dash = get_object_or_404(_visible_dashboards(request.user), pk=pk)
    pids = _dashboard_scope_ids(request.user, dash)
    widgets = [compute_widget(w, pids) for w in (dash.widgets or [])]
    return render(request, "kpi/dashboard_view.html", {
        "dash": dash, "widgets": widgets, "can_edit": dash.owner_id == request.user.id,
    })


@login_required
def dashboard_edit(request, pk=None):
    import json

    from django.shortcuts import get_object_or_404, redirect

    from apps.rbac.permissions import visible_projects

    from .builder import CHARTS, METRIC_CHOICES, PERIODS
    from .models import Dashboard

    dash = get_object_or_404(Dashboard, pk=pk, owner=request.user) if pk else None
    ctx = {
        "dash": dash,
        "projects": visible_projects(request.user).order_by("code"),
        "metric_choices": METRIC_CHOICES, "charts": CHARTS, "periods": PERIODS,
    }
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        try:
            widgets = json.loads(request.POST.get("widgets") or "[]")
        except json.JSONDecodeError:
            widgets = []
        if not name or not widgets:
            ctx["error"] = "Give the dashboard a name and add at least one widget."
            return render(request, "kpi/dashboard_edit.html", ctx)
        proj = None
        if request.POST.get("project"):
            proj = visible_projects(request.user).filter(pk=request.POST["project"]).first()
        if dash is None:
            dash = Dashboard(owner=request.user)
        dash.name = name
        dash.project = proj
        dash.shared = bool(request.POST.get("shared"))
        dash.widgets = widgets
        dash.save()
        return redirect("kpi:dashboard_view", pk=dash.pk)
    return render(request, "kpi/dashboard_edit.html", ctx)


@login_required
def dashboard_delete(request, pk):
    from django.shortcuts import get_object_or_404, redirect
    from django.views.decorators.http import require_POST

    from .models import Dashboard

    if request.method != "POST":
        return redirect("kpi:dashboards")
    get_object_or_404(Dashboard, pk=pk, owner=request.user).delete()
    return redirect("kpi:dashboards")
