"""Read-side KPI computations for the dashboard.

Reads the materialised daily aggregates (apps.kpi.aggregate) for time-series and
volume metrics, plus a few live point-in-time stats (open issues, approval rate)
from the operational tables. Everything is scoped to the projects the user may
see, via rbac.visible_use_cases.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Count, Max, Q, Sum

from apps.rbac.permissions import visible_use_cases
from apps.review.models import ReviewState
from apps.submissions.models import Submission
from apps.validation.models import ValidationFlag, ValidationRule

from .models import EnumeratorKpiDaily, FormKpiDaily, ProjectKpiDaily

PERIODS = {"7": "Last 7 days", "30": "Last 30 days", "90": "Last 90 days", "all": "All time"}


def _since(days: str):
    if days == "all":
        return None
    try:
        return date.today() - timedelta(days=int(days))
    except (TypeError, ValueError):
        return date.today() - timedelta(days=30)


def _q(qs, since, field="date"):
    return qs.filter(**{f"{field}__gte": since}) if since else qs


def overview_metrics(user, days: str = "30") -> dict:
    """Platform-wide (scoped) KPI summary for the Overview page."""
    uc_ids = list(visible_use_cases(user).values_list("id", flat=True))
    since = _since(days)

    proj = _q(ProjectKpiDaily.objects.filter(use_case_id__in=uc_ids), since)
    total_submissions = proj.aggregate(n=Sum("submissions"))["n"] or 0
    active_projects = proj.filter(submissions__gt=0).values("use_case").distinct().count()
    active_forms = (
        _q(FormKpiDaily.objects.filter(form__use_case_id__in=uc_ids), since)
        .filter(submissions__gt=0).values("form").distinct().count()
    )
    active_enumerators = (
        _q(EnumeratorKpiDaily.objects.filter(use_case_id__in=uc_ids), since)
        .filter(submissions__gt=0).values("enumerator").distinct().count()
    )

    # Live point-in-time stats.
    subs = Submission.objects.filter(use_case_id__in=uc_ids)
    total_all = subs.count()
    approved = subs.filter(review__state=ReviewState.APPROVED).count()
    open_issues = ValidationFlag.objects.filter(
        rule__use_case_id__in=uc_ids, status=ValidationFlag.Status.OPEN
    ).count()

    trend = list(
        proj.values("date").annotate(n=Sum("submissions")).order_by("date")
    )
    trend_max = max((t["n"] for t in trend), default=0)
    top_projects = list(
        proj.values("use_case__code", "use_case__name")
        .annotate(n=Sum("submissions")).order_by("-n")[:5]
    )

    return {
        "days": days,
        "period_label": PERIODS.get(days, "Last 30 days"),
        "total_submissions": total_submissions,
        "active_projects": active_projects,
        "active_forms": active_forms,
        "active_enumerators": active_enumerators,
        "open_issues": open_issues,
        "approved_pct": round(approved / total_all * 100) if total_all else 0,
        "quality_score": max(0, 100 - round(open_issues / max(total_all, 1) * 100)),
        "trend": trend,
        "trend_max": trend_max,
        "top_projects": top_projects,
        "top_max": top_projects[0]["n"] if top_projects else 0,
    }


def project_metrics(use_case, days: str = "30") -> dict:
    """Per-project KPI detail."""
    since = _since(days)
    proj = _q(ProjectKpiDaily.objects.filter(use_case=use_case), since)
    total = proj.aggregate(n=Sum("submissions"))["n"] or 0

    subs = Submission.objects.filter(use_case=use_case)
    approved = subs.filter(review__state=ReviewState.APPROVED).count()
    open_issues = ValidationFlag.objects.filter(
        rule__use_case=use_case, status=ValidationFlag.Status.OPEN
    ).count()

    # Collection target across the project's jobs (planned units).
    from apps.fieldwork.models import Job

    target = (
        Job.objects.filter(use_case=use_case).exclude(status="CLOSED")
        .aggregate(t=Sum("target_count"))["t"] or 0
    )

    trend = list(proj.values("date").annotate(n=Sum("submissions")).order_by("date"))
    trend_max = max((t["n"] for t in trend), default=0)
    top_enumerators = list(
        _q(EnumeratorKpiDaily.objects.filter(use_case=use_case), since)
        .values("enumerator__enid", "enumerator__first_name", "enumerator__surname")
        .annotate(n=Sum("submissions")).order_by("-n")[:10]
    )
    forms = list(
        _q(FormKpiDaily.objects.filter(form__use_case=use_case), since)
        .values("form__title", "form__server_form_id", "form__role")
        .annotate(n=Sum("submissions")).order_by("-n")
    )

    return {
        "days": days,
        "period_label": PERIODS.get(days, "Last 30 days"),
        "total_submissions": total,
        "target": target,
        "pct_of_target": round(total / target * 100) if target else 0,
        "approved": approved,
        "open_issues": open_issues,
        "quality_score": max(0, 100 - round(open_issues / max(subs.count(), 1) * 100)),
        "trend": trend,
        "trend_max": trend_max,
        "top_enumerators": top_enumerators,
        "enum_max": top_enumerators[0]["n"] if top_enumerators else 0,
        "forms": forms,
    }


# Severity → bar/heatmap colour (matches the R app's status palette).
SEVERITY_COLORS = {
    ValidationRule.Severity.ERROR: "#c3531f",
    ValidationRule.Severity.WARNING: "#fdb415",
    ValidationRule.Severity.INFO: "#55b047",
}
_SEVERITIES = [
    ValidationRule.Severity.ERROR,
    ValidationRule.Severity.WARNING,
    ValidationRule.Severity.INFO,
]


def quality_metrics(use_case, days: str = "30") -> dict:
    """Data-quality detail: flags by severity, a rule × severity heatmap and the
    worst-offending rules. Flags are attributed to when they were raised."""
    since = _since(days)
    flags = ValidationFlag.objects.filter(rule__use_case=use_case)
    if since:
        flags = flags.filter(created_at__date__gte=since)

    total = flags.count()
    open_n = flags.filter(status=ValidationFlag.Status.OPEN).count()
    resolved_n = flags.filter(status=ValidationFlag.Status.RESOLVED).count()
    waived_n = flags.filter(status=ValidationFlag.Status.WAIVED).count()

    by_severity = {s: flags.filter(severity=s).count() for s in _SEVERITIES}
    sev_max = max(by_severity.values(), default=0)

    # Rule × severity heatmap of OPEN flags — one row per rule that has fired.
    # Cells are an ordered list (aligned to _SEVERITIES) so templates iterate
    # them directly rather than needing a dict-by-key lookup.
    open_flags = flags.filter(status=ValidationFlag.Status.OPEN)
    counts: dict[str, dict] = {}
    for r in (
        open_flags.values("rule__code", "rule__rule_type", "severity")
        .annotate(n=Count("id"))
    ):
        row = counts.setdefault(
            r["rule__code"],
            {"code": r["rule__code"], "rule_type": r["rule__rule_type"],
             "by": dict.fromkeys(_SEVERITIES, 0)},
        )
        row["by"][r["severity"]] = r["n"]
    heatmap = [
        {
            "code": row["code"],
            "rule_type": row["rule_type"],
            "cells": [
                {"severity": s, "n": row["by"][s], "color": SEVERITY_COLORS[s]}
                for s in _SEVERITIES
            ],
            "total": sum(row["by"].values()),
        }
        for row in counts.values()
    ]
    heatmap.sort(key=lambda x: -x["total"])
    cell_max = max((c["n"] for row in heatmap for c in row["cells"]), default=0)

    return {
        "days": days,
        "period_label": PERIODS.get(days, "Last 30 days"),
        "total_flags": total,
        "open_flags": open_n,
        "resolved_flags": resolved_n,
        "waived_flags": waived_n,
        "resolution_rate": round(resolved_n / total * 100) if total else 0,
        "by_severity": [
            {"severity": s, "n": by_severity[s], "color": SEVERITY_COLORS[s]}
            for s in _SEVERITIES
        ],
        "sev_max": sev_max,
        "heatmap": heatmap,
        "cell_max": cell_max,
        "severities": _SEVERITIES,
        "severity_colors": SEVERITY_COLORS,
    }


def enumerator_metrics(use_case, days: str = "30") -> dict:
    """Per-enumerator leaderboard: volume, approval rate, open issues and last
    activity, plus the geo-points the project has collected (for the map)."""
    since = _since(days)
    subs = Submission.objects.filter(use_case=use_case, enumerator__isnull=False)
    if since:
        subs = subs.filter(
            Q(event_date__gte=since)
            | Q(event_date__isnull=True, ona_submission_time__date__gte=since)
        )

    rows = list(
        subs.values("enumerator_id", "enumerator__enid",
                    "enumerator__first_name", "enumerator__surname")
        .annotate(
            n=Count("id"),
            approved=Count("id", filter=Q(review__state=ReviewState.APPROVED)),
            last_active=Max("event_date"),
        )
        .order_by("-n")
    )
    # Open flags per enumerator (separate query to avoid join fan-out).
    open_by_enum = dict(
        ValidationFlag.objects.filter(
            submission__use_case=use_case, status=ValidationFlag.Status.OPEN,
            submission__enumerator__isnull=False,
        )
        .values_list("submission__enumerator_id")
        .annotate(n=Count("id"))
    )
    for r in rows:
        r["open_flags"] = open_by_enum.get(r["enumerator_id"], 0)
        r["approval_pct"] = round(r["approved"] / r["n"] * 100) if r["n"] else 0
    leaderboard_max = rows[0]["n"] if rows else 0

    # Collection points (units the project's submissions touched), for the map.
    points = [
        {"lat": u.lat, "lon": u.lon,
         "label": f"{u.code} · {u.name}" if u.name else u.code, "color": "#55b047"}
        for u in _collected_units(use_case)
    ]

    return {
        "days": days,
        "period_label": PERIODS.get(days, "Last 30 days"),
        "leaderboard": rows,
        "leaderboard_max": leaderboard_max,
        "active_count": len([r for r in rows if r["n"]]),
        "points": points,
    }


def _collected_units(use_case):
    from apps.fieldwork.models import CollectionUnit

    return (
        CollectionUnit.objects.filter(
            use_case=use_case, lat__isnull=False, lon__isnull=False,
            submissions__isnull=False,
        )
        .distinct()
    )


def coverage_metrics(use_case) -> dict:
    """Coverage / gap view: planned units vs collected, per-job progress and a
    map of every known unit coloured by whether data has come in."""
    from apps.fieldwork.models import CollectionUnit
    from apps.fieldwork.services import use_case_jobs_progress

    units = CollectionUnit.objects.filter(use_case=use_case)
    total_units = units.count()
    collected = units.filter(submissions__isnull=False).distinct().count()
    pending = total_units - collected

    jobs = use_case_jobs_progress(use_case)

    mapped = units.filter(lat__isnull=False, lon__isnull=False)
    collected_ids = set(
        mapped.filter(submissions__isnull=False).values_list("id", flat=True)
    )
    points = [
        {"lat": u.lat, "lon": u.lon,
         "label": f"{u.code} · {'collected' if u.id in collected_ids else 'pending'}",
         "color": "#55b047" if u.id in collected_ids else "#fdb415"}
        for u in mapped
    ]

    return {
        "total_units": total_units,
        "collected_units": collected,
        "pending_units": pending,
        "coverage_pct": round(collected / total_units * 100) if total_units else 0,
        "jobs": jobs,
        "points": points,
        "unmapped": total_units - mapped.count(),
    }
