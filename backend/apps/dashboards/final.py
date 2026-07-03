"""Final dataset = submissions that passed review (APPROVED), using their
authoritative (possibly edited) values. This is the clean, reviewed output —
nothing reaches it until a submission is approved.
"""
from __future__ import annotations

from apps.review.models import ReviewState
from apps.submissions.models import Submission


def approved_submissions(project):
    return (
        Submission.objects.filter(project=project, review__state=ReviewState.APPROVED)
        .select_related("enumerator", "collection_unit", "crop", "review", "collected_by")
        .prefetch_related("values")
        .order_by("-event_date", "-ona_submission_time")
    )


def final_rows(project):
    """Return (submissions, field_keys, rows) where each row is
    (submission, {field_key: current_value}). field_keys is the sorted union."""
    subs = list(approved_submissions(project))
    keys: set[str] = set()
    rows = []
    for s in subs:
        values = {v.field_key: v.current_value for v in s.values.all()}
        edited = sum(1 for v in s.values.all() if v.is_edited)
        keys.update(values)
        rows.append({"submission": s, "values": values, "edited": edited})
    return subs, sorted(keys), rows
