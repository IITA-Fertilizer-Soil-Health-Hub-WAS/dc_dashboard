"""Periodic digest of pending reviews, emailed to a use case's reviewers."""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail

from apps.rbac.models import Role, UseCaseMembership
from apps.submissions.models import Submission
from apps.usecases.models import UseCase
from apps.validation.models import ValidationFlag

from .models import ReviewState

logger = logging.getLogger(__name__)

CLOSED = [ReviewState.APPROVED, ReviewState.DECLINED]
# Who gets the pending-review digest: the coordinators (the reviewers).
REVIEWER_ROLES = [
    Role.TRIAL_COORDINATOR,
    Role.COUNTRY_COORDINATOR,
    Role.REGIONAL_COORDINATOR,
]


def pending_summary(use_case) -> dict:
    subs = Submission.objects.filter(use_case=use_case)
    return {
        "pending": subs.exclude(review__state__in=CLOSED).count(),
        "open_issues": ValidationFlag.objects.filter(
            rule__use_case=use_case, status=ValidationFlag.Status.OPEN).count(),
    }


def reviewer_emails(use_case) -> list[str]:
    members = (
        UseCaseMembership.objects.filter(use_case=use_case, role__in=REVIEWER_ROLES)
        .select_related("user")
    )
    return sorted({
        m.user.email for m in members
        if m.user and m.user.is_active and m.user.email
    })


def send_review_digests() -> int:
    """Email each use case's reviewers a summary of work awaiting them.
    Returns the number of emails sent. Skips use cases with nothing pending."""
    sent = 0
    sender = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@fieldbase.local")
    for uc in UseCase.objects.filter(is_active=True):
        summary = pending_summary(uc)
        if not summary["pending"] and not summary["open_issues"]:
            continue
        recipients = reviewer_emails(uc)
        if not recipients:
            continue
        subject = f"[{uc.code}] {summary['pending']} submission(s) awaiting review"
        body = (
            f"{uc.name}: {summary['pending']} submission(s) are awaiting review "
            f"and {summary['open_issues']} issue(s) are open.\n\n"
            f"Open the dashboard to review them."
        )
        try:
            send_mail(subject, body, sender, recipients, fail_silently=True)
            sent += 1
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to send review digest for %s", uc.code)
    return sent
