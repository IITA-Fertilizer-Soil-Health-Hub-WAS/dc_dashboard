"""Health service delivery — the care-management layer (Phase 1).

A CHIS is built on primitives Fieldbase already has: a client is a
``fieldwork.CollectionUnit``, an encounter is a ``submissions.Submission`` (with
its ``event_key`` / ``event_date``), and the visit protocol is the project's
``EventScheduleItem`` schedule. This app adds only what's genuinely new — the
notion that a project *is* a health-service programme, and the client-centric
views over that existing data. See docs/HEALTH_SERVICE_DELIVERY.md for the plan.
"""
from __future__ import annotations

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
