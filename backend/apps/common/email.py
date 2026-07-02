"""Defensive email helper shared by notifications, digests and alerts.

Every outbound email in the platform is best-effort — a mail failure must never
break the action that triggered it (a review transition, an anchor capture, an
alert). This wraps `send_mail` with the project's default sender, `fail_silently`,
and exception logging, returning whether the send was attempted successfully so
callers can keep a sent-count.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def send_safe_email(subject: str, body: str, recipients: list[str], *, context: str = "") -> bool:
    """Send an email to `recipients`; never raise. Returns True if the send was
    dispatched, False if it errored (which is logged). No-op for empty recipients."""
    recipients = [r for r in recipients if r]
    if not recipients:
        return False
    sender = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@fieldbase.local")
    try:
        send_mail(subject, body, sender, recipients, fail_silently=True)
        return True
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to send email%s", f" ({context})" if context else "")
        return False
