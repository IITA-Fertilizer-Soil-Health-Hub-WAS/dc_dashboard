"""The metric + chart registry behind the self-serve dashboard builder.

A dashboard widget is ``{title, metric, chart, period}``. This module knows how
to turn one widget, plus the scope (a set of project ids the viewer may see),
into rendered data the template draws — a single number, a time series, or a
small ranked table. Metrics read the materialised KPI aggregates
(apps.kpi.models) and the live review/flag tables, so the builder never queries
raw submissions directly.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Count, Sum

from apps.review.models import ReviewState
from apps.submissions.models import Submission
from apps.validation.models import ValidationFlag

from .models import EnumeratorKpiDaily, FormKpiDaily, ProjectKpiDaily

PERIODS = {"7": "Last 7 days", "30": "Last 30 days", "90": "Last 90 days", "all": "All time"}
CHARTS = {"number": "Big number", "bar": "Bar chart", "line": "Trend line", "table": "Ranked table"}


def _since(period: str):
    if period == "all":
        return None
    try:
        return date.today() - timedelta(days=int(period))
    except (TypeError, ValueError):
        return date.today() - timedelta(days=30)


def _daily(model, project_ids, since, path="project_id"):
    qs = model.objects.filter(**{f"{path}__in": project_ids})
    if since is not None:
        qs = qs.filter(date__gte=since)
    return qs


# --- metric computers: each returns {kind, ...} ------------------------------
def _submissions_total(pids, since):
    n = _daily(ProjectKpiDaily, pids, since).aggregate(n=Sum("submissions"))["n"] or 0
    return {"kind": "number", "value": n}


def _submissions_series(pids, since):
    rows = (_daily(ProjectKpiDaily, pids, since).values("date")
            .annotate(n=Sum("submissions")).order_by("date"))
    return {"kind": "series",
            "points": [{"label": r["date"].isoformat(), "value": r["n"] or 0} for r in rows]}


def _active_enumerators(pids, since):
    n = (_daily(EnumeratorKpiDaily, pids, since).filter(submissions__gt=0)
         .values("enumerator").distinct().count())
    return {"kind": "number", "value": n}


def _open_issues(pids, since):
    n = ValidationFlag.objects.filter(
        rule__project_id__in=pids, status=ValidationFlag.Status.OPEN).count()
    return {"kind": "number", "value": n}


def _approval_rate(pids, since):
    subs = Submission.objects.filter(project_id__in=pids)
    total = subs.count()
    approved = subs.filter(review__state=ReviewState.APPROVED).count()
    return {"kind": "number", "value": round(100 * approved / total) if total else 0, "suffix": "%"}


def _top_enumerators(pids, since):
    rows = (_daily(EnumeratorKpiDaily, pids, since)
            .values("enumerator__enid").annotate(n=Sum("submissions")).order_by("-n")[:8])
    return {"kind": "rows", "head": ["Enumerator", "Submissions"],
            "rows": [[r["enumerator__enid"] or "—", r["n"] or 0] for r in rows]}


def _top_forms(pids, since):
    rows = (_daily(FormKpiDaily, pids, since, path="form__project_id")
            .values("form__title", "form__ona_form_id")
            .annotate(n=Sum("submissions")).order_by("-n")[:8])
    return {"kind": "rows", "head": ["Form", "Submissions"],
            "rows": [[r["form__title"] or r["form__ona_form_id"] or "—", r["n"] or 0] for r in rows]}


def _care_rollup(pids):
    """Aggregate visit coverage across the care programmes in scope. Returns
    (expected, done, defaulters). Empty when no scoped project is a programme."""
    from apps.care.models import CareProgram
    from apps.care.plan import program_coverage

    exp = done = defaulters = 0
    for prog in CareProgram.objects.filter(project_id__in=pids, is_active=True):
        cov = program_coverage(prog)
        exp += cov["total_expected"]
        done += cov["total_done"]
        defaulters += len(cov["defaulters"])
    return exp, done, defaulters


def _care_coverage(pids, since):
    exp, done, _ = _care_rollup(pids)
    return {"kind": "number", "value": round(100 * done / exp) if exp else 0, "suffix": "%"}


def _care_defaulters(pids, since):
    _, _, defaulters = _care_rollup(pids)
    return {"kind": "number", "value": defaulters}


def _care_enrolled(pids, since):
    from apps.care.models import CareProgram
    from apps.fieldwork.models import CollectionUnit

    prog_pids = CareProgram.objects.filter(
        project_id__in=pids, is_active=True).values_list("project_id", flat=True)
    n = CollectionUnit.objects.filter(project_id__in=list(prog_pids)).count()
    return {"kind": "number", "value": n}


# key -> (label, computer, chart types it makes sense with)
METRICS = {
    "submissions": ("Submissions over time", _submissions_series, ["line", "bar"]),
    "submissions_total": ("Total submissions", _submissions_total, ["number"]),
    "active_enumerators": ("Active enumerators", _active_enumerators, ["number"]),
    "open_issues": ("Open issues", _open_issues, ["number"]),
    "approval_rate": ("Approval rate", _approval_rate, ["number"]),
    "top_enumerators": ("Top enumerators", _top_enumerators, ["table"]),
    "top_forms": ("Top forms", _top_forms, ["table"]),
    # Care follow-up (only meaningful when a scoped project is a care programme).
    "care_coverage": ("Visit coverage (care)", _care_coverage, ["number"]),
    "care_defaulters": ("Overdue-visit clients (care)", _care_defaulters, ["number"]),
    "care_enrolled": ("Enrolled clients (care)", _care_enrolled, ["number"]),
}

METRIC_CHOICES = [(k, v[0]) for k, v in METRICS.items()]


def compute_widget(widget: dict, project_ids) -> dict:
    """Render one widget dict against the scope. Unknown metrics degrade to an
    empty number so a saved dashboard never crashes if a metric is renamed."""
    metric = widget.get("metric")
    entry = METRICS.get(metric)
    period = widget.get("period", "30")
    since = _since(period)
    if entry is None or not project_ids:
        data = {"kind": "number", "value": 0}
    else:
        data = entry[1](list(project_ids), since)
    out = {
        "title": widget.get("title") or (entry[0] if entry else metric or "Metric"),
        "chart": widget.get("chart") or (data.get("kind") == "series" and "line" or "number"),
        "period_label": PERIODS.get(period, ""),
        "data": data,
    }
    if data.get("kind") == "series":
        pts = data.get("points") or []
        vals = [p["value"] for p in pts]
        out["series_max"] = max(vals) if vals else 1
        out["first_label"] = pts[0]["label"] if pts else ""
        out["last_label"] = pts[-1]["label"] if pts else ""
        out["spark_svg"] = _spark_svg(vals)
    return out


def _spark_svg(values, w=240, h=64) -> str:
    """A tiny inline SVG trend line (no external chart lib, CSP-safe)."""
    if not values:
        return ""
    hi = max(values) or 1
    n = len(values)
    step = w / (n - 1) if n > 1 else 0
    pts = " ".join(
        f"{i * step:.1f},{h - 4 - (v / hi) * (h - 8):.1f}" for i, v in enumerate(values)
    )
    last_x = (n - 1) * step
    last_y = h - 4 - (values[-1] / hi) * (h - 8)
    return (
        f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" preserveAspectRatio="none" '
        f'role="img" aria-label="trend">'
        f'<polyline fill="none" stroke="#1a6848" stroke-width="2" stroke-linejoin="round" '
        f'stroke-linecap="round" points="{pts}"/>'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3" fill="#1a6848"/></svg>'
    )
