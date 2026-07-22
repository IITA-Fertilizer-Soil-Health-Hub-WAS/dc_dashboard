"""Submission storage: immutable raw ONA data + an authoritative (editable) layer.

This is the core of the Phase 1 -> Phase 2 design. ``Submission.raw_payload`` and
each ``SubmissionValue.raw_value`` are written once at ingest and never mutated.
Reviewer edits (Phase 5) change only ``SubmissionValue.current_value``. Dashboards
read ``current_value``. Re-ingesting an ONA-edited record refreshes ``raw_value``
but never clobbers an edited ``current_value`` — instead it raises a conflict flag.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel
from apps.projects.models import Crop, FormDefinition, Project, Trial


class Enumerator(BaseModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="enumerators")
    enid = models.CharField(max_length=64)
    first_name = models.CharField(max_length=128, blank=True)
    surname = models.CharField(max_length=128, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    is_test = models.BooleanField(default=False)  # excludes RSENRW000001-style accounts
    # Bridges the ONA-era ENID to a platform account. Once collectors use the
    # mobile app their UserID is stamped directly; until then, linking here lets
    # ingestion resolve collected_by from the enumerator. Optional, set in admin.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="enumerator_profiles",
    )

    class Meta:
        unique_together = ("project", "enid")
        ordering = ["enid"]

    def __str__(self) -> str:
        return self.enid


class Submission(BaseModel):
    """One ONA submission, immutable after ingest. Denormalized fields support
    fast dashboard filtering without re-parsing the payload."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="submissions")
    form = models.ForeignKey(FormDefinition, on_delete=models.CASCADE, related_name="submissions")

    ona_submission_id = models.BigIntegerField(null=True, blank=True)  # ONA "_id"
    ona_uuid = models.CharField(max_length=128)  # ONA "_uuid" — idempotency key
    ona_submission_time = models.DateTimeField(null=True, blank=True)
    ona_edited = models.BooleanField(default=False)

    raw_payload = models.JSONField(default=dict)  # untouched ONA record
    content_hash = models.CharField(max_length=64, db_index=True)  # sha256 of raw_payload

    # Normalized / denormalized for filtering.
    enumerator = models.ForeignKey(
        Enumerator, null=True, blank=True, on_delete=models.SET_NULL, related_name="submissions"
    )
    crop = models.ForeignKey(Crop, null=True, blank=True, on_delete=models.SET_NULL)
    trial = models.ForeignKey(Trial, null=True, blank=True, on_delete=models.SET_NULL)
    event_key = models.CharField(max_length=32, blank=True)
    event_date = models.DateField(null=True, blank=True)

    # The submission's own collected location (from the server's _geolocation or a
    # mapped geopoint), so the actual points can be put on a map.
    lat = models.DecimalField(max_digits=12, decimal_places=7, null=True, blank=True)
    lon = models.DecimalField(max_digits=12, decimal_places=7, null=True, blank=True)

    # The platform identity that collected this submission. Resolved at ingest
    # from the mobile app's stamped UserID, or bridged via the enumerator's
    # linked account during the ONA period. This is what makes the platform the
    # identity registry: every submission traces to a registered user.
    collected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="collected_submissions",
    )

    # The planned collection unit (plot / farmer-household) this submission is
    # for, matched at ingest by its id field — drives expected-vs-actual coverage.
    collection_unit = models.ForeignKey(
        "fieldwork.CollectionUnit",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="submissions",
    )

    ingested_at = models.DateTimeField(auto_now_add=True)

    # SHA-256 of each photo/media attachment's bytes, computed on demand by the
    # media-hashing task. Powers the PHOTO_REUSE integrity check (the same image
    # reused across different farmers is a curbstoning signal). Empty until hashed;
    # `media_hashed_at` marks it as processed (even when there is no media) so the
    # recurring task never re-fetches the same submission.
    media_hashes = models.JSONField(default=list, blank=True)
    media_hashed_at = models.DateTimeField(null=True, blank=True)

    # Write-back: propagating reviewer edits back to the source collection server.
    class WriteBackStatus(models.TextChoices):
        NONE = "NONE", "Not attempted"
        PENDING = "PENDING", "Pending"
        SENT = "SENT", "Sent to source"
        FAILED = "FAILED", "Failed"
        UNSUPPORTED = "UNSUPPORTED", "Unsupported by source"

    writeback_status = models.CharField(
        max_length=12, choices=WriteBackStatus.choices, default=WriteBackStatus.NONE
    )
    writeback_message = models.CharField(max_length=255, blank=True)
    writeback_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "ona_uuid"], name="uq_submission_project_uuid"
            )
        ]
        indexes = [
            models.Index(fields=["project", "event_key"], name="submissions_project_evt_idx"),
            models.Index(fields=["project", "enumerator"], name="submissions_project_enum_idx"),
        ]
        ordering = ["-event_date", "-ona_submission_time"]

    def __str__(self) -> str:
        return f"{self.project.code}:{self.ona_uuid}"

    @property
    def is_corrected(self) -> bool:
        """True if any field was edited by a reviewer during QC (shows a
        'Corrected' badge, mirroring SDMT)."""
        return any(v.is_edited for v in self.values.all())

    @property
    def distance_to_unit_m(self) -> float | None:
        """Metres between where this submission was collected and the assigned
        collection unit's plot location — None unless both have coordinates. The
        basis for the spatial QC flag + the review-screen 'distance from plot' map."""
        from apps.common.geo import haversine_m

        unit = self.collection_unit
        if unit is None or self.lat is None or self.lon is None:
            return None
        if unit.lat is None or unit.lon is None:
            return None
        return haversine_m(self.lat, self.lon, unit.lat, unit.lon)


class SubmissionValue(BaseModel):
    """Field-level authoritative layer. ``raw_value`` is immutable; ``current_value``
    is what dashboards read and what reviewers may edit."""

    class Source(models.TextChoices):
        INGEST = "INGEST", "Ingested from ONA"
        REVIEWER_EDIT = "REVIEWER_EDIT", "Edited by reviewer"
        PLUGIN = "PLUGIN", "Produced by plugin"

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="values")
    field_key = models.CharField(max_length=200)
    raw_value = models.JSONField(null=True, blank=True)  # never changes after ingest
    current_value = models.JSONField(null=True, blank=True)  # authoritative
    is_edited = models.BooleanField(default=False)
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    edited_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.INGEST)

    class Meta:
        unique_together = ("submission", "field_key")
        ordering = ["submission", "field_key"]
        # Cross-project field scans (outlier / unique / reference rules, coverage)
        # filter by field_key; the unique index leads on submission_id so it can't
        # serve those. A field_key index makes them fast at scale.
        indexes = [models.Index(fields=["field_key"])]

    def __str__(self) -> str:
        return f"{self.submission_id}:{self.field_key}"


class CollectorAccount(BaseModel):
    """A platform user's mirrored identity on a collection server.

    When auto-provisioning is on, creating a user (and granting them a project)
    creates or links their account on the project's backend (ODK Central, ONA,
    Kobo) so they can collect without a separate manual signup. One row per
    (user, project) captures the outcome: the server's ``remote_id``/``username``
    and a status. The one-time secret the server generates is **not** stored in
    cleartext — it's surfaced once at provisioning time for an admin to relay.
    ``project`` is null for a server-wide account created at user-creation time
    before any project grant.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACTIVE = "ACTIVE", "Active"
        LINKED = "LINKED", "Linked (already existed)"
        FAILED = "FAILED", "Failed"
        UNSUPPORTED = "UNSUPPORTED", "Backend has no provisioning"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="collector_accounts"
    )
    project = models.ForeignKey(
        Project, null=True, blank=True, on_delete=models.CASCADE,
        related_name="collector_accounts",
    )
    backend = models.CharField(max_length=32)  # backend type: ONA / ODK_CENTRAL / KOBO
    remote_id = models.CharField(max_length=128, blank=True)
    username = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    message = models.TextField(blank=True)
    provisioned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # One row per (user, project); NULLs are distinct on most DBs, so the
            # server-wide (project=NULL) row is kept unique by the app's
            # get_or_create keyed on (user, project=None).
            models.UniqueConstraint(
                fields=["user", "project"],
                condition=models.Q(project__isnull=False),
                name="uniq_collector_account_user_project",
            ),
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(project__isnull=True),
                name="uniq_collector_account_user_serverwide",
            ),
        ]
        ordering = ["user", "project"]

    def __str__(self) -> str:
        scope = self.project.code if self.project_id else "(server-wide)"
        return f"{self.user} @ {self.backend}/{scope} = {self.status}"
