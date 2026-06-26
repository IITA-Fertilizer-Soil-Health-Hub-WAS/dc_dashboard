"""Role-based access control, scoped per use case.

The R app had no roles: Auth0 `eia_apps` metadata simply listed which use cases
a user could see. Here, access is a (user, use_case, role) triple. Platform
Admin is global (Django superuser). All other roles are granted per use case.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel
from apps.usecases.models import UseCase


class Role(models.TextChoices):
    PLATFORM_ADMIN = "PLATFORM_ADMIN", "Platform Admin"
    REGIONAL_COORDINATOR = "REGIONAL_COORDINATOR", "Regional Coordinator"
    COUNTRY_COORDINATOR = "COUNTRY_COORDINATOR", "Country Coordinator"
    TRIAL_COORDINATOR = "TRIAL_COORDINATOR", "Trial / Survey Coordinator"
    SURVEY_DOMAIN_EXPERT = "SURVEY_DOMAIN_EXPERT", "Survey Domain Expert"
    QUALITY_CHECK = "QUALITY_CHECK", "Quality Check / Agronomist"
    ENUMERATOR = "ENUMERATOR", "Enumerator"
    VIEWER = "VIEWER", "Viewer"


class UseCaseMembership(BaseModel):
    """Grants a user a role within a single use case. The unit of authorization."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    use_case = models.ForeignKey(UseCase, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=32, choices=Role.choices)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="granted_memberships",
    )

    class Meta:
        unique_together = ("user", "use_case", "role")
        ordering = ["use_case", "role"]

    def __str__(self) -> str:
        return f"{self.user} @ {self.use_case} = {self.role}"
