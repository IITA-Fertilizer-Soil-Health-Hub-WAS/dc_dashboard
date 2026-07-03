"""Role-based access control, scoped per use case.

The R app had no roles: Auth0 `eia_apps` metadata simply listed which use cases
a user could see. Here, access is a (user, project, role) triple. Platform
Admin is global (Django superuser). All other roles are granted per use case.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.common.models import BaseModel
from apps.usecases.models import Country, Project, Region


class Role(models.TextChoices):
    PLATFORM_ADMIN = "PLATFORM_ADMIN", "Platform Admin"
    REGIONAL_COORDINATOR = "REGIONAL_COORDINATOR", "Regional Coordinator"
    COUNTRY_COORDINATOR = "COUNTRY_COORDINATOR", "Country Coordinator"
    TRIAL_COORDINATOR = "TRIAL_COORDINATOR", "Trial / Survey Coordinator"
    ENUMERATOR = "ENUMERATOR", "Enumerator"
    VIEWER = "VIEWER", "Viewer"


class UseCaseMembership(BaseModel):
    """Grants a user a role at one scope level: a use case, a country, or a region.

    The unit of authorization. A country grant cascades to every use case in that
    country; a region grant cascades to every use case in the region. Exactly one
    of ``project`` / ``country`` / ``region`` is set (enforced by a check
    constraint). The cascade is resolved in ``permissions.roles_for`` /
    ``visible_projects`` so views never special-case the scope level.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    # Exactly one of these three scopes is non-null.
    project = models.ForeignKey(
        Project, null=True, blank=True, on_delete=models.CASCADE, related_name="memberships"
    )
    country = models.ForeignKey(
        Country, null=True, blank=True, on_delete=models.CASCADE, related_name="memberships"
    )
    region = models.ForeignKey(
        Region, null=True, blank=True, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=32, choices=Role.choices)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="granted_memberships",
    )

    class Meta:
        ordering = ["project", "country", "region", "role"]
        constraints = [
            # Exactly one scope level must be set.
            models.CheckConstraint(
                name="membership_exactly_one_scope",
                check=(
                    Q(project__isnull=False, country__isnull=True, region__isnull=True)
                    | Q(project__isnull=True, country__isnull=False, region__isnull=True)
                    | Q(project__isnull=True, country__isnull=True, region__isnull=False)
                ),
            ),
            # One row per (user, role) at each scope level.
            models.UniqueConstraint(
                fields=["user", "project", "role"],
                condition=Q(project__isnull=False),
                name="uniq_membership_project",
            ),
            models.UniqueConstraint(
                fields=["user", "country", "role"],
                condition=Q(country__isnull=False),
                name="uniq_membership_country",
            ),
            models.UniqueConstraint(
                fields=["user", "region", "role"],
                condition=Q(region__isnull=False),
                name="uniq_membership_region",
            ),
        ]

    @property
    def scope(self):
        """The object this membership is scoped to (use case, country, or region)."""
        return self.project or self.country or self.region

    def __str__(self) -> str:
        return f"{self.user} @ {self.scope} = {self.role}"


class UseCaseAccessRequest(BaseModel):
    """A user's self-service request to join a use case they can see in their
    institution. A coordinator with authority over that use case approves (which
    creates the membership) or declines it from Team & access."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        DECLINED = "DECLINED", "Declined"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="access_requests"
    )
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="access_requests"
    )
    note = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="decided_access_requests",
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # At most one open request per user per use case.
            models.UniqueConstraint(
                fields=["user", "project"],
                condition=Q(status="PENDING"),
                name="uniq_pending_access_request",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} -> {self.project} ({self.status})"
