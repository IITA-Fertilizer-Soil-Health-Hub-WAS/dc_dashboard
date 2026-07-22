"""Close the loop with the field: get the issues flagged on a submission back to
the enumerator who collected it, so data quality improves at the source instead
of only being caught in review.
"""
from __future__ import annotations

from django.db.models import Q

from apps.common.email import send_safe_email
from apps.validation.models import ValidationFlag


def open_corrections(user):
    """Open validation flags on submissions this user collected — what they need
    to fix, newest first."""
    return (
        ValidationFlag.objects.filter(status=ValidationFlag.Status.OPEN)
        .filter(Q(submission__collected_by=user) | Q(submission__enumerator__user=user))
        .select_related("submission", "submission__project", "rule")
        .order_by("-created_at")
    )


def _collectors_with_open_flags() -> set:
    """User ids that collected at least one currently-flagged submission."""
    base = ValidationFlag.objects.filter(status=ValidationFlag.Status.OPEN)
    ids = set(
        base.filter(submission__collected_by__isnull=False)
        .values_list("submission__collected_by_id", flat=True)
    )
    ids |= set(
        base.filter(submission__enumerator__user__isnull=False)
        .values_list("submission__enumerator__user_id", flat=True)
    )
    return {i for i in ids if i}


def send_correction_digests(limit_per_user: int = 30) -> int:
    """Email each enumerator the open issues on their own submissions. Returns
    the number of emails sent (skips anyone with nothing to fix / no email)."""
    from apps.accounts.models import User

    sent = 0
    for user in (
        User.objects.filter(id__in=_collectors_with_open_flags(), is_active=True)
        .exclude(email="")
    ):
        flags = list(open_corrections(user)[:limit_per_user])
        if not flags:
            continue
        lines = [
            f"  - [{f.submission.project.code}] {f.field_key or 'record'}: {f.message}"
            for f in flags
        ]
        subject = f"[Fieldbase] {len(flags)} correction(s) needed on your submissions"
        body = (
            "Some of the data you collected has been flagged and needs a look:\n\n"
            + "\n".join(lines)
            + "\n\nOpen “My submissions” in Fieldbase to review and fix them."
        )
        if send_safe_email(subject, body, [user.email], context="correction digest"):
            sent += 1
    return sent
