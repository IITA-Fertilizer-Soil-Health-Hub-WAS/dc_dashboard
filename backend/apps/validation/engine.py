"""Validation engine: run a use case's enabled rules and reconcile flags.

Per rule, it computes the set of flags that *should* exist now, then upserts
them and auto-resolves any prior flags from that rule that no longer fire
(idempotent re-runs). Submissions that end up with an open ERROR flag are moved
to FLAGGED via the review service.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.review.services import system_flag
from apps.submissions.models import Submission

from . import rules as rule_impls
from .models import ValidationFlag, ValidationRule

# Rules evaluated once per submission.
PER_SUBMISSION = {
    ValidationRule.RuleType.REGEX_ID: rule_impls.regex_id,
    ValidationRule.RuleType.REQUIRED_FIELD: rule_impls.required_field,
    ValidationRule.RuleType.NUMERIC_RANGE: rule_impls.numeric_range,
    ValidationRule.RuleType.GEO_DISTANCE: rule_impls.geo_distance,
    ValidationRule.RuleType.GEO_CONTAINMENT: rule_impls.geo_containment,
}
# Rules evaluated once per use case (need the whole timeline).
PER_USE_CASE = {
    ValidationRule.RuleType.EVENT_SEQUENCE: rule_impls.event_sequence,
    ValidationRule.RuleType.DATE_WINDOW: rule_impls.date_window,
}


@dataclass
class ValidationStats:
    use_case: str
    opened: int = 0
    resolved: int = 0
    flagged_submissions: int = 0


def _run_rule(rule: ValidationRule, submissions) -> list[rule_impls.FlagResult]:
    if rule.rule_type in PER_SUBMISSION:
        fn = PER_SUBMISSION[rule.rule_type]
        results: list[rule_impls.FlagResult] = []
        for sub in submissions:
            results.extend(fn(sub, rule.params))
        return results
    if rule.rule_type in PER_USE_CASE:
        return PER_USE_CASE[rule.rule_type](rule.use_case, rule.params)
    return []  # PLUGIN / CROSS_FIELD handled by plugin.post_validate (Phase 8)


@transaction.atomic
def run_for_use_case(use_case) -> ValidationStats:
    stats = ValidationStats(use_case=use_case.code)
    submissions = list(
        Submission.objects.filter(use_case=use_case).select_related("collection_unit")
    )
    error_submission_ids: set = set()

    for rule in use_case.rules.filter(is_enabled=True):
        results = _run_rule(rule, submissions)
        wanted: dict[tuple, rule_impls.FlagResult] = {
            (r.submission_id, r.field_key): r for r in results
        }

        # Auto-resolve flags from this rule that no longer fire.
        existing = ValidationFlag.objects.filter(rule=rule, status=ValidationFlag.Status.OPEN)
        for flag in existing:
            key = (flag.submission_id, flag.field_key)
            if key not in wanted:
                flag.status = ValidationFlag.Status.RESOLVED
                flag.resolved_at = timezone.now()
                flag.save(update_fields=["status", "resolved_at", "updated_at"])
                stats.resolved += 1

        # Upsert wanted flags.
        for (submission_id, field_key), res in wanted.items():
            flag, created = ValidationFlag.objects.update_or_create(
                submission_id=submission_id,
                rule=rule,
                field_key=field_key,
                defaults={
                    "message": res.message,
                    "severity": rule.severity,
                    "detail": res.detail,
                    "status": ValidationFlag.Status.OPEN,
                },
            )
            if created:
                stats.opened += 1
            if rule.severity == ValidationRule.Severity.ERROR and rule.auto_flag_state:
                error_submission_ids.add(submission_id)

    # Move freshly-flagged submissions to FLAGGED.
    for sub in submissions:
        if sub.id in error_submission_ids:
            review = system_flag(sub, note="auto-flagged by validation")
            if review.state == "FLAGGED":
                stats.flagged_submissions += 1

    return stats


def run_for_submission(submission) -> None:
    """Convenience: re-run per-submission rules for a single submission."""
    run_for_use_case(submission.use_case)
