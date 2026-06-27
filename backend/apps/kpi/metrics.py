"""Read-side KPI computations for the dashboard.

Reads the materialised daily aggregates (apps.kpi.aggregate) for time-series and
volume metrics, plus a few live point-in-time stats (open issues, approval rate)
from the operational tables. Everything is scoped to the projects the user may
see, via rbac.visible_use_cases.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Sum

from apps.rbac.permissions import visible_use_cases
from apps.review.models import ReviewState
from apps.submissions.models import Submission
from apps.validation.models import ValidationFlag

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
