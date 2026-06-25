"""Review service layer — the only sanctioned way to mutate review state.

Every function: (1) checks the actor's role via rbac.user_can, (2) validates the
transition against the state machine, (3) writes an append-only ReviewActionLog,
and (4) updates state — all in one transaction. The API and dashboards call
these; they never poke Review.state directly.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.rbac.permissions import user_can
from apps.submissions.models import Submission, SubmissionValue

from .models import Review, ReviewAction, ReviewActionLog, ReviewState
from .state_machine import ReviewPermissionDenied, resolve


def get_or_create_review(submission: Submission) -> Review:
    review, _ = Review.objects.get_or_create(submission=submission)
    return review


@transaction.atomic
def _transition(
    *,
    user,
    submission: Submission,
    action: str,
    note: str = "",
    field_key: str = "",
    old_value=None,
    new_value=None,
) -> Review:
    review = get_or_create_review(submission)
    transition = resolve(action, review.state)

    if transition.permission is not None and not user_can(
        user, transition.permission, submission.use_case
    ):
        raise ReviewPermissionDenied(
            f"{getattr(user, 'email', user)} cannot {action} in {submission.use_case.code}"
        )

    from_state = review.state
    to_state = transition.to_state or from_state

    ReviewActionLog.objects.create(
        submission=submission,
        actor=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        from_state=from_state,
        to_state=to_state,
        field_key=field_key,
        old_value=old_value,
        new_value=new_value,
        note=note,
    )

    if transition.to_state is not None:
        review.state = to_state
    if action == ReviewAction.QC_APPROVE:
        review.qc_signed_by = user
        review.qc_signed_at = timezone.now()
    review.save()
    return review


# --- Public reviewer actions -------------------------------------------------

def open_review(user, submission, note: str = "") -> Review:
    return _transition(user=user, submission=submission, action=ReviewAction.OPEN_REVIEW, note=note)


def request_edit(user, submission, note: str = "") -> Review:
    return _transition(
        user=user, submission=submission, action=ReviewAction.REQUEST_EDIT, note=note
    )


def decline(user, submission, note: str = "") -> Review:
    return _transition(user=user, submission=submission, action=ReviewAction.DECLINE, note=note)


def qc_approve(user, submission, note: str = "") -> Review:
    review = _transition(
        user=user, submission=submission, action=ReviewAction.QC_APPROVE, note=note
    )
    # On approval, propagate the authoritative (reviewed) values to the source.
    _enqueue_writeback(submission)
    return review


def _enqueue_writeback(submission) -> None:
    """Push reviewer edits back to the source server (async; no-op if disabled)."""
    from apps.ingestion.tasks import writeback_submission_task

    writeback_submission_task.delay(str(submission.pk))


def reopen(user, submission, note: str = "") -> Review:
    return _transition(user=user, submission=submission, action=ReviewAction.REOPEN, note=note)


def comment(user, submission, note: str) -> Review:
    return _transition(user=user, submission=submission, action=ReviewAction.COMMENT, note=note)


@transaction.atomic
def assign(user, submission, assignee) -> Review:
    """Assign a submission to a reviewer (not a state transition). Coordinators
    and QC may assign; the assignee is notified by email."""
    if not user_can(user, "open_review", submission.use_case):
        raise ReviewPermissionDenied(
            f"{getattr(user, 'email', user)} cannot assign in {submission.use_case.code}"
        )
    review = get_or_create_review(submission)
    review.assigned_to = assignee
    review.save(update_fields=["assigned_to", "updated_at"])
    ReviewActionLog.objects.create(
        submission=submission, actor=user, action=ReviewAction.ASSIGN,
        from_state=review.state, to_state=review.state,
        note=f"Assigned to {getattr(assignee, 'email', assignee)}",
    )
    from .notifications import notify_assignment
    notify_assignment(submission, assignee)
    return review


def system_flag(submission, note: str = "") -> Review:
    """Move a fresh (INGESTED) submission to FLAGGED. Called by the validation
    engine when an ERROR-severity rule produces an open flag. No-op if the
    submission has already advanced past INGESTED."""
    review = get_or_create_review(submission)
    if review.state != ReviewState.INGESTED:
        return review
    return _transition(
        user=None, submission=submission, action=ReviewAction.SYSTEM_FLAG, note=note
    )


@transaction.atomic
def edit_value(user, submission, field_key: str, new_value, note: str = "") -> Review:
    """Edit a field's authoritative value. Updates current_value only (raw_value
    is immutable), records old/new in the audit log, and moves state to EDITED."""
    value = SubmissionValue.objects.select_for_update().filter(
        submission=submission, field_key=field_key
    ).first()
    old = value.current_value if value else None

    review = _transition(
        user=user,
        submission=submission,
        action=ReviewAction.EDIT_VALUE,
        note=note,
        field_key=field_key,
        old_value=old,
        new_value=new_value,
    )

    # Permission/transition passed — apply the edit.
    if value is None:
        value = SubmissionValue(submission=submission, field_key=field_key, raw_value=None)
    value.current_value = new_value
    value.is_edited = True
    value.edited_by = user
    value.edited_at = timezone.now()
    value.source = SubmissionValue.Source.REVIEWER_EDIT
    value.save()

    # The submission now diverges from the source — mark for write-back.
    from apps.ingestion.writeback import mark_pending

    mark_pending(submission)
    return review
