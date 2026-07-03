"""Reviewer notifications. Email failures must never break the review action."""
from __future__ import annotations

from apps.common.email import send_safe_email


def notify_assignment(submission, assignee) -> None:
    if not getattr(assignee, "email", None):
        return
    uc = submission.project
    subject = f"[{uc.code}] A submission was assigned to you for review"
    body = (
        f"You have been assigned submission {submission.ona_uuid} "
        f"({uc.name}) for review.\n\n"
        f"Open the dashboard to review and act on it."
    )
    send_safe_email(subject, body, [assignee.email], context="assignment notification")
