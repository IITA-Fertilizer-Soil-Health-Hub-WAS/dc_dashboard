"""Reviewer notifications. Email failures must never break the review action."""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def notify_assignment(submission, assignee) -> None:
    if not getattr(assignee, "email", None):
        return
    uc = submission.use_case
    subject = f"[{uc.code}] A submission was assigned to you for review"
    body = (
        f"You have been assigned submission {submission.ona_uuid} "
        f"({uc.name}) for review.\n\n"
        f"Open the dashboard to review and act on it."
    )
    try:
        send_mail(
            subject, body,
            getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@eia.local"),
            [assignee.email], fail_silently=True,
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to send assignment notification")
