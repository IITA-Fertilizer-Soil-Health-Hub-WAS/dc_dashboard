"""M&E analytics: materialised daily KPI aggregates + alert rules.

Mirrors the doc's kpi_analytics schema, but populated in-app (we already ingest
into Postgres, so no separate ETL service): a Celery Beat task rebuilds these
daily aggregates on a schedule, and submission webhooks can trigger an immediate
refresh. Point-in-time KPIs (quality score, coverage) are computed live on top
of these; the daily rows are the expensive-to-recompute time series.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel
from apps.projects.models import FormDefinition, Project
from apps.submissions.models import Enumerator


class ProjectKpiDaily(BaseModel):
    """One row per project per day."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="kpi_daily")
    date = models.DateField(db_index=True)
    submissions = models.PositiveIntegerField(default=0)
    active_enumerators = models.PositiveIntegerField(default=0)
    flags_opened = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("project", "date")
        ordering = ["-date"]
        indexes = [models.Index(fields=["project", "date"], name="kpi_project_proj_date_idx")]

    def __str__(self) -> str:
        return f"{self.project.code}@{self.date}: {self.submissions}"


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
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="enumerator_kpi_daily"
    )
    date = models.DateField(db_index=True)
    submissions = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("enumerator", "project", "date")
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

    project = models.ForeignKey(
        Project, null=True, blank=True, on_delete=models.CASCADE, related_name="alert_rules"
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
        ordering = ["project", "name"]

    def __str__(self) -> str:
        return self.name


class AlertEvent(BaseModel):
    """A fired alert — append-only log."""

    rule = models.ForeignKey(AlertRule, on_delete=models.CASCADE, related_name="events")
    project = models.ForeignKey(
        Project, null=True, blank=True, on_delete=models.SET_NULL, related_name="alert_events"
    )
    observed_value = models.FloatField(null=True, blank=True)
    severity = models.CharField(max_length=8, choices=AlertRule.Severity.choices)
    message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.severity}: {self.message[:60]}"


class Dashboard(BaseModel):
    """A self-serve analytics dashboard a user assembles from metric widgets.

    Unlike the fixed KPI screens, a Dashboard is user-authored: pick a scope (one
    project or all the projects you can see), then add widgets (a metric + a chart
    type + a period). Widgets are stored as a JSON list rather than a child table
    so the whole layout saves in one write and reorders freely. Owner-private by
    default; ``shared`` exposes it read-only to the owner's institution.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dashboards"
    )
    name = models.CharField(max_length=200)
    # Scope: a single project, or null = across everything the viewer can see.
    project = models.ForeignKey(
        Project, null=True, blank=True, on_delete=models.CASCADE, related_name="dashboards"
    )
    shared = models.BooleanField(default=False)  # visible to the owner's institution
    # [{title, metric, chart, period}] — see apps.kpi.builder.
    widgets = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
