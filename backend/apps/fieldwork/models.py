"""Field-work planning: collection units + jobs.

A **collection unit** is the thing data is collected on — a plot, or a
farmer/household (one type per project, set on ``Project.unit_type``). A **job**
is a data-collection assignment: a form to collect, a target, a deadline, and the
enumerators assigned over a set of units. Submissions are matched back to their
unit at ingest, so the platform tracks expected vs actual — the basis for the
Coverage and Timeliness KPIs.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel
from apps.usecases.models import FormDefinition, Project


class CollectionUnit(BaseModel):
    """One plot or farmer/household enrolled for collection in a project."""

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="collection_units"
    )
    code = models.CharField(max_length=64)  # matches a submission ID field (e.g. HHID/plot id)
    name = models.CharField(max_length=255, blank=True)
    # Operative point: the GIS centroid until the coordinator captures the farmer
    # anchor in the field, then the captured anchor (the spatial-check reference).
    lat = models.DecimalField(max_digits=12, decimal_places=7, null=True, blank=True)
    lon = models.DecimalField(max_digits=12, decimal_places=7, null=True, blank=True)
    # Elected plot outline (GeoJSON), for the point-in-polygon containment check.
    boundary = models.JSONField(default=dict, blank=True)
    anchor_captured = models.BooleanField(default=False)
    anchor_captured_at = models.DateTimeField(null=True, blank=True)
    anchor_captured_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="captured_anchors",
    )
    alt = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    country = models.CharField(max_length=64, blank=True)
    region = models.CharField(max_length=64, blank=True)
    district = models.CharField(max_length=64, blank=True)
    # The schedule anchor (the household "site selection" / verification date) —
    # DATE_WINDOW offsets are counted from here for units that carry it.
    site_selection_date = models.DateField(null=True, blank=True)
    # The field-staff member who registered this unit (denormalised from ingest).
    enumerator = models.ForeignKey(
        "submissions.Enumerator", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="collection_units",
    )
    attributes = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ("project", "code")
        ordering = ["project", "code"]

    def __str__(self) -> str:
        return self.code


class Job(BaseModel):
    """A data-collection assignment for a project: a form to collect, a target,
    a deadline, the assigned enumerators, and the units to cover."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        CLOSED = "CLOSED", "Closed"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="jobs")
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
    # Closure: a job is wrapped up with an optional note (who/when/why).
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="closed_jobs",
    )
    closure_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.project.code}:{self.name}"

    def close(self, user, note: str = "") -> None:
        from django.utils import timezone

        self.status = self.Status.CLOSED
        self.closed_by = user if getattr(user, "is_authenticated", False) else None
        self.closed_at = timezone.now()
        self.closure_note = note
        self.save(update_fields=["status", "closed_by", "closed_at", "closure_note", "updated_at"])


class CandidatePlot(BaseModel):
    """A plot proposed by the upstream GIS site-selection tool. Each trial gets a
    small set (typically 3 primary + 1 backup) as GeoJSON polygons with accessibility
    / cropping-region attributes. The country coordinator elects ONE per trial (a web
    decision, ground-truthed in the field); the elected candidate is promoted to a
    CollectionUnit. See project memory: plot-election governance."""

    class Role(models.TextChoices):
        PRIMARY = "PRIMARY", "Primary"
        BACKUP = "BACKUP", "Backup"

    class Status(models.TextChoices):
        PROPOSED = "PROPOSED", "Proposed"
        ELECTED = "ELECTED", "Elected"
        NOT_SELECTED = "NOT_SELECTED", "Not selected"

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="candidate_plots"
    )
    # The trial / area this candidate belongs to — the key the GIS export must carry.
    trial_key = models.CharField(max_length=64)
    candidate_ref = models.CharField(max_length=32)  # e.g. "A" / "B" / "C" / plot code
    role = models.CharField(max_length=8, choices=Role.choices, default=Role.PRIMARY)
    rank = models.PositiveIntegerField(default=0)  # GIS rank; 1 = recommended
    accessibility = models.CharField(max_length=32, blank=True)
    cropping_region = models.CharField(max_length=128, blank=True)
    geometry = models.JSONField(default=dict, blank=True)  # GeoJSON Polygon / MultiPolygon
    centroid_lat = models.DecimalField(max_digits=12, decimal_places=7, null=True, blank=True)
    centroid_lon = models.DecimalField(max_digits=12, decimal_places=7, null=True, blank=True)
    properties = models.JSONField(default=dict, blank=True)  # any other GIS attributes

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PROPOSED)
    # Election audit (set in the coordinator election step).
    elected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="elected_plots",
    )
    elected_at = models.DateTimeField(null=True, blank=True)
    election_note = models.CharField(max_length=255, blank=True)
    # The unit created when this candidate is elected.
    collection_unit = models.ForeignKey(
        CollectionUnit, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="source_candidate",
    )

    class Meta:
        unique_together = ("project", "trial_key", "candidate_ref")
        ordering = ["project", "trial_key", "rank", "candidate_ref"]
        indexes = [models.Index(fields=["project", "trial_key"], name="fieldwork_cand_project_idx")]

    def __str__(self) -> str:
        return f"{self.project.code}:{self.trial_key}:{self.candidate_ref}"


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
