"""Outbound ETL: push a project's cleaned, reviewed data to configured
destinations (a warehouse loader, an ETL tool's HTTP source, an iPaaS webhook).

Incremental by design — each push sends only submissions changed since the last
successful one (tracked per destination as a cursor) so it scales and is idempotent
for the consumer to upsert on the submission uuid.
"""
from __future__ import annotations

from django.utils import timezone


def _row(s) -> dict:
    return {
        "uuid": s.ona_uuid,
        "form": s.form.server_ref if s.form_id else None,
        "event": s.event_key,
        "event_date": s.event_date.isoformat() if s.event_date else None,
        "enumerator": s.enumerator.enid if s.enumerator_id else None,
        "collection_unit": s.collection_unit.code if s.collection_unit_id else None,
        "lat": s.lat, "lon": s.lon,
        "review_state": getattr(getattr(s, "review", None), "state", None),
        "updated_at": s.updated_at.isoformat(),
        "values": {v.field_key: v.current_value for v in s.values.all()},
    }


def pending_for(dest, *, limit=1000):
    """Submissions this destination hasn't pushed yet (approved-only if set),
    oldest change first so the cursor advances monotonically."""
    from apps.submissions.models import Submission

    qs = (Submission.objects.filter(project=dest.project)
          .select_related("form", "enumerator", "collection_unit", "review")
          .prefetch_related("values"))
    if dest.only_approved:
        qs = qs.filter(review__state="APPROVED")
    if dest.cursor:
        qs = qs.filter(updated_at__gt=dest.cursor)
    return list(qs.order_by("updated_at")[:limit])


def push_destination(dest, *, limit=1000, dry_run=False) -> dict:
    """Send the pending rows to one destination; record + advance the cursor on
    success. Never raises — records the error on the destination instead."""
    import httpx

    subs = pending_for(dest, limit=limit)
    if not subs:
        return {"sent": 0, "status": "OK", "message": "nothing new"}
    payload = {
        "project": dest.project.code,
        "count": len(subs),
        "submissions": [_row(s) for s in subs],
    }
    if dry_run:
        return {"sent": len(subs), "status": "DRY", "sample": payload["submissions"][:2]}

    headers = {"Content-Type": "application/json"}
    if dest.secret:
        headers["Authorization"] = f"Bearer {dest.secret}"
    try:
        resp = httpx.post(dest.url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        dest.cursor = subs[-1].updated_at
        dest.last_status = dest.Status.OK
        dest.last_message = f"{len(subs)} row(s) → HTTP {resp.status_code}"
        result = {"sent": len(subs), "status": "OK"}
    except Exception as exc:
        dest.last_status = dest.Status.ERROR
        dest.last_message = str(exc)[:500]
        result = {"sent": 0, "status": "ERROR", "message": str(exc)[:200]}
    dest.last_run_at = timezone.now()
    dest.save(update_fields=["cursor", "last_status", "last_message", "last_run_at",
                             "updated_at"])
    return result


def push_project(project) -> list[dict]:
    """Push every active destination of a project (called after a sync/approval)."""
    out = []
    for dest in project.destinations.filter(is_active=True):
        out.append({"destination": dest.name, **push_destination(dest)})
    return out
