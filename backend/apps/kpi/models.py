"""M&E analytics: materialised daily KPI aggregates + alert rules.

Mirrors the doc's kpi_analytics schema, but populated in-app (we already ingest
into Postgres, so no separate ETL service): a Celery Beat task rebuilds these
daily aggregates on a schedule, and submission webhooks can trigger an immediate
refresh. Point-in-time KPIs (quality score, coverage) are computed live on top
of these; the daily rows are the expensive-to-recompute time series.
"""
from __future__ import annotations

from django.db import models

from apps.common.models import BaseModel
from apps.submissions.models import Enumerator
from apps.usecases.models import FormDefinition, UseCase


class ProjectKpiDaily(BaseModel):
    """One row per project per day."""

    use_case = models.ForeignKey(UseCase, on_delete=models.CASCADE, related_name="kpi_daily")
    date = models.DateField(db_index=True)
    submissions = models.PositiveIntegerField(default=0)
    active_enumerators = models.PositiveIntegerField(default=0)
    flags_opened = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("use_case", "date")
        ordering = ["-date"]
        indexes = [models.Index(fields=["use_case", "date"])]

    def __str__(self) -> str:
        return f"{self.use_case.code}@{self.date}: {self.submissions}"


class FormKpiDaily(BaseModel):
    """One row per form per day."""

    form = models.ForeignKey(FormDefinition, on_delete=models.CASCADE, related_name="kpi_daily")
    date = models.DateField(db_index=True)
    submissions = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("form", "date")
        ordering = ["-date"]


class EnumeratorKpiDaily(BaseModel):
    """One row per enumerator per project per day."""

    enumerator = models.ForeignKey(
        Enumerator, on_delete=models.CASCADE, related_name="kpi_daily"
    )
    use_case = models.ForeignKey(
        UseCase, on_delete=models.CASCADE, related_name="enumerator_kpi_daily"
    )
    date = models.DateField(db_index=True)
    submissions = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("enumerator", "use_case", "date")
        ordering = ["-date"]


class AlertRule(BaseModel):
    """A threshold rule on a KPI metric (evaluated in Stage C4)."""

    class Comparator(models.TextChoices):
        LT = "LT", "is below"
        LTE = "LTE", "is at or below"
        GT = "GT", "is above"
        GTE = "GTE", "is at or above"

    class Severity(models.TextChoices):
        INFO = "INFO", "Informational"
        WARNING = "WARNING", "Warning"
        CRITICAL = "CRITICAL", "Critical"

    use_case = models.ForeignKey(
        UseCase, null=True, blank=True, on_delete=models.CASCADE, related_name="alert_rules"
    )  # null = platform-wide
    name = models.CharField(max_length=255)
    metric = models.CharField(max_length=64, default="daily_submissions")
    comparator = models.CharField(max_length=4, choices=Comparator.choices, default=Comparator.LT)
    threshold = models.FloatField(default=0)
    consecutive_days = models.PositiveIntegerField(default=1)
    severity = models.CharField(max_length=8, choices=Severity.choices, default=Severity.WARNING)
    is_enabled = models.BooleanField(default=True)
    notify_emails = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["use_case", "name"]

    def __str__(self) -> str:
        return self.name


class AlertEvent(BaseModel):
    """A fired alert — append-only log."""

    rule = models.ForeignKey(AlertRule, on_delete=models.CASCADE, related_name="events")
    use_case = models.ForeignKey(
        UseCase, null=True, blank=True, on_delete=models.SET_NULL, related_name="alert_events"
    )
    observed_value = models.FloatField(null=True, blank=True)
    severity = models.CharField(max_length=8, choices=AlertRule.Severity.choices)
    message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.severity}: {self.message[:60]}"
