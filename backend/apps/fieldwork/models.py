"""Field-work planning: collection units + jobs.

A **collection unit** is the thing data is collected on — a plot, or a
farmer/household (one type per project, set on ``UseCase.unit_type``). A **job**
is a data-collection assignment: a form to collect, a target, a deadline, and the
enumerators assigned over a set of units. Submissions are matched back to their
unit at ingest, so the platform tracks expected vs actual — the basis for the
Coverage and Timeliness KPIs.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel
from apps.usecases.models import FormDefinition, UseCase


class CollectionUnit(BaseModel):
    """One plot or farmer/household enrolled for collection in a project."""

    use_case = models.ForeignKey(
        UseCase, on_delete=models.CASCADE, related_name="collection_units"
    )
    code = models.CharField(max_length=64)  # matches a submission ID field (e.g. HHID/plot id)
    name = models.CharField(max_length=255, blank=True)
    lat = models.DecimalField(max_digits=12, decimal_places=7, null=True, blank=True)
    lon = models.DecimalField(max_digits=12, decimal_places=7, null=True, blank=True)
    country = models.CharField(max_length=64, blank=True)
    region = models.CharField(max_length=64, blank=True)
    district = models.CharField(max_length=64, blank=True)
    attributes = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ("use_case", "code")
        ordering = ["use_case", "code"]

    def __str__(self) -> str:
        return self.code


class Job(BaseModel):
    """A data-collection assignment for a project: a form to collect, a target,
    a deadline, the assigned enumerators, and the units to cover."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        CLOSED = "CLOSED", "Closed"

    use_case = models.ForeignKey(UseCase, on_delete=models.CASCADE, related_name="jobs")
    name = models.CharField(max_length=255)
    form = models.ForeignKey(
        FormDefinition, null=True, blank=True, on_delete=models.SET_NULL, related_name="jobs"
    )
    target_count = models.PositiveIntegerField(default=0)
    start_date = models.DateField(null=True, blank=True)
    deadline = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    assigned_to = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="jobs"
    )
    units = models.ManyToManyField(
        CollectionUnit, through="UnitAssignment", blank=True, related_name="jobs"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="created_jobs",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.use_case.code}:{self.name}"


class UnitAssignment(BaseModel):
    """Which enumerator is responsible for which unit within a job."""

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="assignments")
    unit = models.ForeignKey(
        CollectionUnit, on_delete=models.CASCADE, related_name="assignments"
    )
    enumerator = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="unit_assignments",
    )

    class Meta:
        unique_together = ("job", "unit")
        ordering = ["job", "unit"]

    def __str__(self) -> str:
        return f"{self.job.name}:{self.unit.code}"
