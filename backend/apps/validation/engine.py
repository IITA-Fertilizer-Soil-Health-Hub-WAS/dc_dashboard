"""Validation engine: run a project's enabled rules and reconcile flags.

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
    ValidationRule.RuleType.CROSS_FIELD: rule_impls.cross_field,
    ValidationRule.RuleType.CONDITIONAL_REQ: rule_impls.conditional_required,
    ValidationRule.RuleType.MEDIA_REQUIRED: rule_impls.media_required,
    ValidationRule.RuleType.GEO_DISTANCE: rule_impls.geo_distance,
    ValidationRule.RuleType.GEO_CONTAINMENT: rule_impls.geo_containment,
}
# Rules evaluated once per project (need the whole timeline / distribution).
PER_USE_CASE = {
    ValidationRule.RuleType.EVENT_SEQUENCE: rule_impls.event_sequence,
    ValidationRule.RuleType.DATE_WINDOW: rule_impls.date_window,
    ValidationRule.RuleType.NUMERIC_OUTLIER: rule_impls.numeric_outlier,
    ValidationRule.RuleType.UNIQUE_FIELD: rule_impls.unique_field,
    ValidationRule.RuleType.REFERENCE_MATCH: rule_impls.reference_match,
    ValidationRule.RuleType.REFERENCE_COMPARE: rule_impls.reference_compare,
    ValidationRule.RuleType.GEO_DUPLICATE: rule_impls.geo_duplicate,
    ValidationRule.RuleType.SUBMISSION_SPEED: rule_impls.submission_speed,
    ValidationRule.RuleType.PHOTO_REUSE: rule_impls.photo_reuse,
}


@dataclass
class ValidationStats:
    project: str
    opened: int = 0
    resolved: int = 0
    flagged_submissions: int = 0


def _run_rule(rule: ValidationRule, submissions) -> list[rule_impls.FlagResult]:
    if rule.rule_type in PER_SUBMISSION:
        fn = PER_SUBMISSION[rule.rule_type]
        # A form-scoped rule only evaluates that form's submissions.
        subs = ([s for s in submissions if s.form_id == rule.form_id]
                if rule.form_id else submissions)
        results: list[rule_impls.FlagResult] = []
        for sub in subs:
            results.extend(fn(sub, rule.params))
        return results
    if rule.rule_type in PER_USE_CASE:
        return PER_USE_CASE[rule.rule_type](rule.project, rule.params, form=rule.form)
    return []  # PLUGIN handled by plugin.post_validate (Phase 8)


def _attach_value_cache(project, submissions) -> None:
    """Bulk-load every SubmissionValue for the project once and attach a
    {field_key: value} dict to each submission, so per-submission rules do O(1)
    lookups instead of a query per field (the N+1 that blocked scale)."""
    from collections import defaultdict

    from apps.submissions.models import SubmissionValue

    vmap: dict = defaultdict(dict)
    for sid, fk, cv in (
        SubmissionValue.objects.filter(submission__project=project)
        .values_list("submission_id", "field_key", "current_value").iterator()
    ):
        vmap[sid][fk] = cv
    for sub in submissions:
        sub._value_cache = vmap.get(sub.id, {})


@transaction.atomic
def run_for_project(project) -> ValidationStats:
    stats = ValidationStats(project=project.code)
    submissions = list(
        Submission.objects.filter(project=project).select_related("collection_unit")
    )
    _attach_value_cache(project, submissions)
    error_submission_ids: set = set()

    for rule in project.rules.filter(is_enabled=True):
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
    run_for_project(submission.project)
