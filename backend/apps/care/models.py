"""Health service delivery — the care-management layer (Phase 1).

A CHIS is built on primitives Fieldbase already has: a client is a
``fieldwork.CollectionUnit``, an encounter is a ``submissions.Submission`` (with
its ``event_key`` / ``event_date``), and the visit protocol is the project's
``EventScheduleItem`` schedule. This app adds only what's genuinely new — the
notion that a project *is* a health-service programme, and the client-centric
views over that existing data. See docs/HEALTH_SERVICE_DELIVERY.md for the plan.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel
from apps.projects.models import Project


class CareProgram(BaseModel):
    """Marks a project as a health-service programme and holds care-specific
    presentation (what a 'client' is called). One programme per project."""

    project = models.OneToOneField(
        Project, on_delete=models.CASCADE, related_name="care_program"
    )
    name = models.CharField(max_length=200, blank=True)
    # What a beneficiary is called in this programme (Client / Patient / Household).
    client_label = models.CharField(max_length=40, default="Client")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["project"]

    def __str__(self) -> str:
        return self.name or f"Care: {self.project.code}"

    @property
    def client_label_plural(self) -> str:
        label = self.client_label or "Client"
        return label + ("es" if label.lower().endswith("s") else "s")


class CareAssignment(BaseModel):
    """Assigns a client (CollectionUnit) to a health worker in a programme.

    The caseload link. Reassigning is a *referral*: the old row is deactivated
    and a new one created, so the chain of who-held-this-client is preserved.
    Exactly one active assignment per client at a time.
    """

    program = models.ForeignKey(
        CareProgram, on_delete=models.CASCADE, related_name="assignments"
    )
    unit = models.ForeignKey(
        "fieldwork.CollectionUnit", on_delete=models.CASCADE, related_name="care_assignments"
    )
    worker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="care_caseload"
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="care_referrals_made",
    )
    note = models.CharField(max_length=255, blank=True)  # referral reason
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["unit"], condition=models.Q(is_active=True),
                name="uniq_active_care_assignment_per_unit",
            ),
        ]
        indexes = [models.Index(fields=["worker", "is_active"])]

    def __str__(self) -> str:
        return f"{self.unit.code} → {self.worker}"
