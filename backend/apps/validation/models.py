"""Validation configuration.

ValidationRule is part of a use case's declarative config (authored via YAML or
the Admin UI). The engine that executes these rules and produces ValidationFlag
rows lands in Phase 6; ValidationFlag (which references a Submission) is added
once the submissions models exist.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel
from apps.submissions.models import Submission
from apps.usecases.models import UseCase


class ValidationRule(BaseModel):
    """A declarative validation rule for a use case.

    Reproduces and extends the R checks: REGEX_ID (was `!grepl(patternissues,...)`),
    EVENT_SEQUENCE (out-of-order events), DATE_WINDOW (the green/amber/red/purple
    status from dynamic_colorcodeS), plus new NUMERIC_RANGE / REQUIRED_FIELD.
    """

    class RuleType(models.TextChoices):
        REGEX_ID = "REGEX_ID", "Regex ID check"
        EVENT_SEQUENCE = "EVENT_SEQUENCE", "Event sequence check"
        DATE_WINDOW = "DATE_WINDOW", "Date-window / schedule check"
        NUMERIC_RANGE = "NUMERIC_RANGE", "Numeric range / outlier check"
        REQUIRED_FIELD = "REQUIRED_FIELD", "Required field present"
        CROSS_FIELD = "CROSS_FIELD", "Cross-field check"
        GEO_DISTANCE = "GEO_DISTANCE", "GPS distance from assigned plot"
        GEO_CONTAINMENT = "GEO_CONTAINMENT", "GPS inside the elected plot boundary"
        PLUGIN = "PLUGIN", "Plugin-provided check"

    class Severity(models.TextChoices):
        INFO = "INFO", "Info"
        WARNING = "WARNING", "Warning"
        ERROR = "ERROR", "Error"

    use_case = models.ForeignKey(UseCase, on_delete=models.CASCADE, related_name="rules")
    code = models.SlugField(max_length=64)
    rule_type = models.CharField(max_length=20, choices=RuleType.choices)
    params = models.JSONField(default=dict, blank=True)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.WARNING)
    # When an ERROR-severity rule produces an open flag, auto-move the review to FLAGGED.
    auto_flag_state = models.BooleanField(default=True)
    is_enabled = models.BooleanField(default=True)

    class Meta:
        unique_together = ("use_case", "code")
        ordering = ["use_case", "code"]

    def __str__(self) -> str:
        return f"{self.use_case.code}:{self.code}({self.rule_type})"


class ValidationFlag(BaseModel):
    """A problem found on a submission by a rule. Feeds both the Issues view and
    the review workflow (an open ERROR flag forces the review to FLAGGED).

    Unique on (submission, rule, field_key) so re-running the engine upserts
    rather than duplicating, and a rule that no longer fires auto-resolves."""

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        RESOLVED = "RESOLVED", "Resolved"
        WAIVED = "WAIVED", "Waived"

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="flags")
    rule = models.ForeignKey(ValidationRule, on_delete=models.CASCADE, related_name="flags")
    message = models.CharField(max_length=255)
    severity = models.CharField(max_length=10, choices=ValidationRule.Severity.choices)
    field_key = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    detail = models.JSONField(default=dict, blank=True)  # expected vs actual, dates, etc.
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("submission", "rule", "field_key")
        ordering = ["submission", "rule"]
        indexes = [models.Index(fields=["status", "severity"])]

    def __str__(self) -> str:
        return f"{self.rule.code}:{self.message}"
