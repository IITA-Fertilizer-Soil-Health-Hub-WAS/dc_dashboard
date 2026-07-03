"""Threshold-alert engine: evaluate AlertRules against current KPIs, log
AlertEvents and email watchers.

A rule names a metric (e.g. daily_submissions, open_flags, coverage_pct), a
comparator and a threshold. Point-in-time metrics fire on the current value;
`daily_submissions` additionally requires the breach to hold for
`consecutive_days` running days (catches a project that has gone quiet).

Evaluation is idempotent for a given day: a rule that is already breached does
not re-fire (and re-email) until a day with no AlertEvent for that rule+project.
Runs on Beat (hourly) and can be triggered after an aggregate rebuild.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Sum

from apps.common.email import send_safe_email
from apps.projects.models import Project
from apps.validation.models import ValidationFlag

from .models import AlertEvent, AlertRule, ProjectKpiDaily

# Human labels for the supported metrics (also used by the rule admin/help).
METRICS = {
    "daily_submissions": "Daily submissions",
    "open_flags": "Open quality flags",
    "coverage_pct": "Coverage %",
    "active_enumerators": "Active enumerators (latest day)",
    "worsening_enumerators": "Enumerators with worsening quality",
    "project_quality_worsening": "Project quality trend worsening (1/0)",
}

# An enumerator needs at least this many submissions in the trend window before a
# "worsening" direction is trusted (a couple of flagged records isn't a trend).
MIN_TREND_VOLUME = 8

_CMP = {
    AlertRule.Comparator.LT: lambda v, t: v < t,
    AlertRule.Comparator.LTE: lambda v, t: v <= t,
    AlertRule.Comparator.GT: lambda v, t: v > t,
    AlertRule.Comparator.GTE: lambda v, t: v >= t,
}


def _breaches(value: float, comparator: str, threshold: float) -> bool:
    return _CMP.get(comparator, _CMP[AlertRule.Comparator.LT])(value, threshold)


def _daily_submission_series(project, days: int) -> list[int]:
    """Submission counts for the last `days` calendar days (oldest→newest),
    filling gaps with 0 so a silent day counts as a breach."""
    today = date.today()
    start = today - timedelta(days=days - 1)
    rows = dict(
        ProjectKpiDaily.objects.filter(project=project, date__gte=start)
        .values_list("date").annotate(n=Sum("submissions"))
    )
    return [rows.get(start + timedelta(days=i), 0) for i in range(days)]


def _coverage_pct(project) -> float:
    from .metrics import coverage_metrics

    return coverage_metrics(project)["coverage_pct"]


def _worsening_enumerators(project) -> list[str]:
    """Enumerators whose flag-rate trend is worsening (with enough volume to trust),
    each as 'ENID (early%→recent%)' — the early-warning list the alert reports."""
    from apps.submissions.models import Enumerator

    from .metrics import enumerator_trend

    out: list[str] = []
    enums = (
        Enumerator.objects.filter(project=project, is_test=False, submissions__isnull=False)
        .distinct()
    )
    for enum in enums:
        t = enumerator_trend(project, enum.id)
        if t["direction"] == "worsening" and t["total_n"] >= MIN_TREND_VOLUME:
            out.append(f"{enum.enid} ({t['early_pct']}%→{t['recent_pct']}%)")
    return out


def evaluate_rule_for_project(rule: AlertRule, project) -> AlertEvent | None:
    """Evaluate one rule against one project; create+return an AlertEvent if it
    breaches and hasn't already fired today, else None."""
    metric = rule.metric
    if metric == "daily_submissions":
        n = max(1, rule.consecutive_days)
        series = _daily_submission_series(project, n)
        if not all(_breaches(v, rule.comparator, rule.threshold) for v in series):
            return None
        observed = float(series[-1])
        detail = f"{n} consecutive day(s); latest {observed:g}/day"
    elif metric == "open_flags":
        observed = float(
            ValidationFlag.objects.filter(
                rule__project=project, status=ValidationFlag.Status.OPEN
            ).count()
        )
        if not _breaches(observed, rule.comparator, rule.threshold):
            return None
        detail = f"{observed:g} open flag(s)"
    elif metric == "coverage_pct":
        observed = float(_coverage_pct(project))
        if not _breaches(observed, rule.comparator, rule.threshold):
            return None
        detail = f"coverage {observed:g}%"
    elif metric == "active_enumerators":
        latest = (
            ProjectKpiDaily.objects.filter(project=project)
            .order_by("-date").values_list("active_enumerators", flat=True).first()
        )
        observed = float(latest or 0)
        if not _breaches(observed, rule.comparator, rule.threshold):
            return None
        detail = f"{observed:g} active enumerator(s) on the latest day"
    elif metric == "worsening_enumerators":
        worsening = _worsening_enumerators(project)
        observed = float(len(worsening))
        if not _breaches(observed, rule.comparator, rule.threshold):
            return None
        detail = "worsening: " + (", ".join(worsening) if worsening else "none")
    elif metric == "project_quality_worsening":
        from .metrics import project_quality_trend

        t = project_quality_trend(project)
        worsening = t["direction"] == "worsening" and t["total_n"] >= MIN_TREND_VOLUME
        observed = 1.0 if worsening else 0.0
        if not _breaches(observed, rule.comparator, rule.threshold):
            return None
        detail = f"project flag rate {t['early_pct']}%→{t['recent_pct']}% (earlier vs recent half)"
    else:  # unknown metric — skip safely
        return None

    # Idempotent per day: don't re-fire if this rule already fired for this
    # project today.
    if AlertEvent.objects.filter(
        rule=rule, project=project, created_at__date=date.today()
    ).exists():
        return None

    label = METRICS.get(metric, metric)
    comparator_label = rule.get_comparator_display()
    message = (
        f"[{project.code}] {rule.name}: {label} {comparator_label} "
        f"{rule.threshold:g} — {detail}."
    )
    return AlertEvent.objects.create(
        rule=rule, project=project, observed_value=observed,
        severity=rule.severity, message=message,
    )


def run_alerts() -> dict[str, int]:
    """Evaluate every enabled rule and email watchers about new events.

    A project-scoped rule runs against its own project; a platform-wide rule
    (project is null) runs against every active project. Returns counts of
    events fired and emails sent."""
    fired = 0
    emailed = 0
    for rule in AlertRule.objects.filter(is_enabled=True).select_related("project"):
        targets = [rule.project] if rule.project_id else list(
            Project.objects.filter(is_active=True)
        )
        for uc in targets:
            if uc is None:
                continue
            event = evaluate_rule_for_project(rule, uc)
            if event is None:
                continue
            fired += 1
            recipients = [e for e in (rule.notify_emails or []) if e]
            if send_safe_email(
                f"[{rule.severity}] {uc.code}: {rule.name}", event.message, recipients,
                context=f"alert {rule.name}",
            ):
                emailed += 1
    return {"events": fired, "emails": emailed}
