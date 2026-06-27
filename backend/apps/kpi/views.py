"""M&E KPI dashboard — Overview + per-project pages (role-scoped)."""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.dashboards.scoping import get_scoped_use_case

from .metrics import PERIODS, overview_metrics, project_metrics


@login_required
def kpi_overview(request):
    days = request.GET.get("days", "30")
    if days not in PERIODS:
        days = "30"
    ctx = overview_metrics(request.user, days) | {"periods": PERIODS}
    return render(request, "kpi/overview.html", ctx)


@login_required
def kpi_project(request, code):
    uc = get_scoped_use_case(request, code)  # 404 if not visible to the user
    days = request.GET.get("days", "30")
    if days not in PERIODS:
        days = "30"
    ctx = project_metrics(uc, days) | {"uc": uc, "periods": PERIODS}
    return render(request, "kpi/project.html", ctx)
