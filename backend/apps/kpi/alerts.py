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

import logging
from datetime import date, timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Sum

from apps.usecases.models import UseCase
from apps.validation.models import ValidationFlag

from .models import AlertEvent, AlertRule, ProjectKpiDaily

logger = logging.getLogger(__name__)

# Human labels for the supported metrics (also used by the rule admin/help).
METRICS = {
    "daily_submissions": "Daily submissions",
    "open_flags": "Open quality flags",
    "coverage_pct": "Coverage %",
    "active_enumerators": "Active enumerators (latest day)",
}

_CMP = {
    AlertRule.Comparator.LT: lambda v, t: v < t,
    AlertRule.Comparator.LTE: lambda v, t: v <= t,
    AlertRule.Comparator.GT: lambda v, t: v > t,
    AlertRule.Comparator.GTE: lambda v, t: v >= t,
}


def _breaches(value: float, comparator: str, threshold: float) -> bool:
    return _CMP.get(comparator, _CMP[AlertRule.Comparator.LT])(value, threshold)


def _daily_submission_series(use_case, days: int) -> list[int]:
    """Submission counts for the last `days` calendar days (oldest→newest),
    filling gaps with 0 so a silent day counts as a breach."""
    today = date.today()
    start = today - timedelta(days=days - 1)
    rows = dict(
        ProjectKpiDaily.objects.filter(use_case=use_case, date__gte=start)
        .values_list("date").annotate(n=Sum("submissions"))
    )
    return [rows.get(start + timedelta(days=i), 0) for i in range(days)]


def _coverage_pct(use_case) -> float:
    from .metrics import coverage_metrics

    return coverage_metrics(use_case)["coverage_pct"]


def evaluate_rule_for_use_case(rule: AlertRule, use_case) -> AlertEvent | None:
    """Evaluate one rule against one project; create+return an AlertEvent if it
    breaches and hasn't already fired today, else None."""
    metric = rule.metric
    if metric == "daily_submissions":
        n = max(1, rule.consecutive_days)
        series = _daily_submission_series(use_case, n)
        if not all(_breaches(v, rule.comparator, rule.threshold) for v in series):
            return None
        observed = float(series[-1])
        detail = f"{n} consecutive day(s); latest {observed:g}/day"
    elif metric == "open_flags":
        observed = float(
            ValidationFlag.objects.filter(
                rule__use_case=use_case, status=ValidationFlag.Status.OPEN
            ).count()
        )
        if not _breaches(observed, rule.comparator, rule.threshold):
            return None
        detail = f"{observed:g} open flag(s)"
    elif metric == "coverage_pct":
        observed = float(_coverage_pct(use_case))
        if not _breaches(observed, rule.comparator, rule.threshold):
            return None
        detail = f"coverage {observed:g}%"
    elif metric == "active_enumerators":
        latest = (
            ProjectKpiDaily.objects.filter(use_case=use_case)
            .order_by("-date").values_list("active_enumerators", flat=True).first()
        )
        observed = float(latest or 0)
        if not _breaches(observed, rule.comparator, rule.threshold):
            return None
        detail = f"{observed:g} active enumerator(s) on the latest day"
    else:  # unknown metric — skip safely
        return None

    # Idempotent per day: don't re-fire if this rule already fired for this
    # project today.
    if AlertEvent.objects.filter(
        rule=rule, use_case=use_case, created_at__date=date.today()
    ).exists():
        return None

    label = METRICS.get(metric, metric)
    comparator_label = rule.get_comparator_display()
    message = (
        f"[{use_case.code}] {rule.name}: {label} {comparator_label} "
        f"{rule.threshold:g} — {detail}."
    )
    return AlertEvent.objects.create(
        rule=rule, use_case=use_case, observed_value=observed,
        severity=rule.severity, message=message,
    )


def run_alerts() -> dict[str, int]:
    """Evaluate every enabled rule and email watchers about new events.

    A project-scoped rule runs against its own project; a platform-wide rule
    (use_case is null) runs against every active project. Returns counts of
    events fired and emails sent."""
    fired = 0
    emailed = 0
    sender = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@eia.local")
    for rule in AlertRule.objects.filter(is_enabled=True).select_related("use_case"):
        targets = [rule.use_case] if rule.use_case_id else list(
            UseCase.objects.filter(is_active=True)
        )
        for uc in targets:
            if uc is None:
                continue
            event = evaluate_rule_for_use_case(rule, uc)
            if event is None:
                continue
            fired += 1
            recipients = [e for e in (rule.notify_emails or []) if e]
            if recipients:
                try:
                    send_mail(
                        f"[{rule.severity}] {uc.code}: {rule.name}",
                        event.message, sender, recipients, fail_silently=True,
                    )
                    emailed += 1
                except Exception:  # pragma: no cover - defensive
                    logger.exception("Failed to send alert email for %s", rule.name)
    return {"events": fired, "emails": emailed}
