"""Periodic digest of pending reviews, emailed to a use case's reviewers."""
from __future__ import annotations

from apps.common.email import send_safe_email
from apps.projects.models import Project
from apps.rbac.models import Role, UseCaseMembership
from apps.submissions.models import Submission
from apps.validation.models import ValidationFlag

from .models import REVIEW_CLOSED_STATES

CLOSED = REVIEW_CLOSED_STATES
# Who gets the pending-review digest: the coordinators (the reviewers).
REVIEWER_ROLES = [
    Role.TRIAL_COORDINATOR,
    Role.COUNTRY_COORDINATOR,
    Role.REGIONAL_COORDINATOR,
]


def pending_summary(project) -> dict:
    subs = Submission.objects.filter(project=project)
    return {
        "pending": subs.exclude(review__state__in=CLOSED).count(),
        "open_issues": ValidationFlag.objects.filter(
            rule__project=project, status=ValidationFlag.Status.OPEN).count(),
    }


def reviewer_emails(project) -> list[str]:
    members = (
        UseCaseMembership.objects.filter(project=project, role__in=REVIEWER_ROLES)
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
    for uc in Project.objects.filter(is_active=True):
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
        if send_safe_email(subject, body, recipients, context=f"review digest {uc.code}"):
            sent += 1
    return sent
