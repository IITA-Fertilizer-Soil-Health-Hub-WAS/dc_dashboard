"""Observability for ingestion — a record of every sync so failures are never
silent (surfaced on the System status page and alerted on)."""
from __future__ import annotations

from django.db import models

from apps.common.models import BaseModel
from apps.projects.models import Project


class SyncRun(BaseModel):
    """One execution of a project sync: when, how it was triggered, the outcome,
    and the counts. `created_at` is the start time; `finished_at` the end."""

    class Status(models.TextChoices):
        RUNNING = "RUNNING", "Running"
        OK = "OK", "OK"
        ERROR = "ERROR", "Error"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="sync_runs")
    trigger = models.CharField(max_length=20, default="scheduled")  # scheduled/manual/webhook
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING)
    finished_at = models.DateTimeField(null=True, blank=True)
    created = models.PositiveIntegerField(default=0)
    updated = models.PositiveIntegerField(default=0)
    unchanged = models.PositiveIntegerField(default=0)
    message = models.TextField(blank=True)  # error detail when status = ERROR

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["project", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.project.code} {self.status} @ {self.created_at:%Y-%m-%d %H:%M}"

    @property
    def duration_s(self) -> float | None:
        if self.finished_at:
            return round((self.finished_at - self.created_at).total_seconds(), 1)
        return None
