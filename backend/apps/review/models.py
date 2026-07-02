"""Submission review workflow: state + append-only audit log.

The R app only *flagged* issues visually; nothing could be declined, edited, or
signed off. Here every submission has a Review (its current state) and an
immutable trail of ReviewActions. Who may perform each transition is enforced by
the state machine via the rbac `user_can` facade.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel
from apps.submissions.models import Submission
from apps.usecases.models import UseCase


class RejectionReason(BaseModel):
    """A configurable reason a submission can be declined for — so rejections are
    categorised (and reportable) instead of only a free-text note. Adapted from
    SDMT's rejection-reason taxonomy. `use_case` null = available to every project."""

    use_case = models.ForeignKey(
        UseCase, null=True, blank=True, on_delete=models.CASCADE,
        related_name="rejection_reasons",
    )
    code = models.SlugField(max_length=64)
    label = models.CharField(max_length=255)
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "label"]
        unique_together = ("use_case", "code")

    def __str__(self) -> str:
        return self.label


class ReviewState(models.TextChoices):
    INGESTED = "INGESTED", "Ingested"
    FLAGGED = "FLAGGED", "Flagged"
    IN_REVIEW = "IN_REVIEW", "In review"
    EDIT_REQUESTED = "EDIT_REQUESTED", "Edit requested"
    EDITED = "EDITED", "Edited"
    DECLINED = "DECLINED", "Declined"
    QC_PENDING = "QC_PENDING", "QC pending"
    APPROVED = "APPROVED", "Approved"
    SUPERSEDED = "SUPERSEDED", "Superseded"


# Terminal review states — a submission whose review has been finalised. Shared by
# the dashboards, projects landing and digests so the "in review" filter agrees.
REVIEW_CLOSED_STATES = [ReviewState.APPROVED, ReviewState.DECLINED]


class ReviewAction(models.TextChoices):
    OPEN_REVIEW = "OPEN_REVIEW", "Open review"
    REQUEST_EDIT = "REQUEST_EDIT", "Request edit"
    EDIT_VALUE = "EDIT_VALUE", "Edit value"
    DECLINE = "DECLINE", "Decline"
    ENDORSE = "ENDORSE", "Endorse (level 1)"
    QC_APPROVE = "QC_APPROVE", "Validate (final)"
    REOPEN = "REOPEN", "Reopen"
    COMMENT = "COMMENT", "Comment"
    SUPERSEDE = "SUPERSEDE", "Supersede"
    SYSTEM_FLAG = "SYSTEM_FLAG", "System flag"
    ASSIGN = "ASSIGN", "Assign"


class Review(BaseModel):
    """Current review state of a submission (one per submission)."""

    submission = models.OneToOneField(
        Submission, on_delete=models.CASCADE, related_name="review"
    )
    state = models.CharField(
        max_length=20, choices=ReviewState.choices, default=ReviewState.INGESTED
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_reviews",
    )
    # Gate 1: the Trial/Country Coordinator who endorsed (first-level sign-off).
    endorsed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="endorsed_reviews",
    )
    endorsed_at = models.DateTimeField(null=True, blank=True)
    # Gate 2: the Regional Coordinator who gave final validation.
    qc_signed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="qc_signed_reviews",
    )
    qc_signed_at = models.DateTimeField(null=True, blank=True)
    # Why the submission was declined (categorised), set on the DECLINE action.
    rejection_reason = models.ForeignKey(
        RejectionReason, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="reviews",
    )

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["state"])]

    def __str__(self) -> str:
        return f"Review({self.submission.ona_uuid}={self.state})"


class ReviewActionLog(BaseModel):
    """Append-only audit entry. Never updated or deleted."""

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="actions")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=20, choices=ReviewAction.choices)
    from_state = models.CharField(max_length=20, blank=True)
    to_state = models.CharField(max_length=20, blank=True)
    field_key = models.CharField(max_length=64, blank=True)  # for EDIT_VALUE
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.action}@{self.submission_id}"
