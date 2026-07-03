"""Write-back: propagate reviewer edits to the source collection server.

When a submission is approved (or edited), its authoritative edited values should
be reflected in the original record on ONA / Kobo / ODK Central / etc. This is
backend-specific and potentially destructive, so it is:

* gated by ``settings.WRITEBACK_ENABLED`` (default off),
* only attempted when the backend reports ``supports_writeback``, and
* fully tracked on the Submission (status + message + timestamp).

When disabled or unsupported, edits are recorded as PENDING so they're visible
and can be flushed later once write-back is enabled for that backend.
"""
from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from apps.submissions.models import Submission

from .backends.registry import get_backend_for


def collect_changes(submission: Submission) -> dict:
    """The authoritative edited values to push (field_key -> current_value)."""
    return {
        v.field_key: v.current_value
        for v in submission.values.filter(is_edited=True)
    }


def push_submission(submission: Submission) -> Submission:
    """Attempt to write a submission's edits back to its source. Records status."""
    changes = collect_changes(submission)
    Status = Submission.WriteBackStatus

    if not changes:
        submission.writeback_status = Status.NONE
        submission.writeback_message = "No edits to propagate"
        submission.save(update_fields=["writeback_status", "writeback_message", "updated_at"])
        return submission

    backend = get_backend_for(submission.project)

    if not getattr(backend, "supports_writeback", False):
        submission.writeback_status = Status.UNSUPPORTED
        submission.writeback_message = f"{backend.label or backend.type} has no write-back"
    elif not getattr(settings, "WRITEBACK_ENABLED", False):
        submission.writeback_status = Status.PENDING
        submission.writeback_message = "Queued — write-back disabled (WRITEBACK_ENABLED=false)"
    else:
        result = backend.push_edit(submission, changes)
        if result.ok:
            submission.writeback_status = Status.SENT
            submission.writeback_message = result.message or "Synced to source"
            submission.writeback_at = timezone.now()
        else:
            submission.writeback_status = Status.FAILED
            submission.writeback_message = result.message or "Write-back failed"

    submission.save(
        update_fields=["writeback_status", "writeback_message", "writeback_at", "updated_at"]
    )
    return submission


def mark_pending(submission: Submission, reason: str = "Edited — awaiting propagation") -> None:
    """Flag that a submission has unsynced edits (called when a value is edited)."""
    submission.writeback_status = Submission.WriteBackStatus.PENDING
    submission.writeback_message = reason
    submission.save(update_fields=["writeback_status", "writeback_message", "updated_at"])
