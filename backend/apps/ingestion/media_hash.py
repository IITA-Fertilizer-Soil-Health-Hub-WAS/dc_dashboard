"""Hash a submission's photo/media bytes for the PHOTO_REUSE integrity check.

Bytes are never stored (privacy + size) — we keep only the SHA-256 of each image,
fetched through the backend's authenticated proxy. Two submissions carrying the
same hash hold the same photo; when they belong to different farmers that is a
strong curbstoning signal (see the PHOTO_REUSE validation rule).
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from django.utils import timezone

logger = logging.getLogger(__name__)


def hash_submission_media(submission, backend=None) -> list[str]:
    """Fetch each image attachment on `submission`, SHA-256 its bytes, and store the
    sorted, de-duplicated list on `submission.media_hashes`. Best-effort: an
    attachment that will not fetch is skipped, never fatal. Returns the hashes."""
    if backend is None:
        from apps.ingestion.backends.registry import get_backend_for

        backend = get_backend_for(submission.use_case)

    try:
        attachments = backend.list_attachments(submission)
    except Exception:  # pragma: no cover - defensive
        logger.exception("list_attachments failed for %s", submission.pk)
        return list(submission.media_hashes or [])

    hashes: set[str] = set()
    for att in attachments:
        if not att.get("is_image"):
            continue
        try:
            data, _ctype = backend.fetch_attachment(att)
        except Exception:
            logger.warning("fetch_attachment failed for %s / %s", submission.pk, att.get("name"))
            continue
        if data:
            hashes.add(hashlib.sha256(data).hexdigest())

    ordered = sorted(hashes)
    submission.media_hashes = ordered
    submission.media_hashed_at = timezone.now()  # processed — don't re-fetch next run
    submission.save(update_fields=["media_hashes", "media_hashed_at", "updated_at"])
    return ordered


@dataclass
class MediaHashStats:
    processed: int = 0
    with_media: int = 0


def hash_use_case_media(use_case, *, limit: int | None = None, only_new: bool = True) -> MediaHashStats:
    """Hash media for a project's submissions. `only_new` skips those already hashed
    so re-runs are cheap; `limit` caps the batch (media fetches are network-bound)."""
    from apps.submissions.models import Submission

    qs = Submission.objects.filter(use_case=use_case).order_by("-ingested_at")
    if only_new:
        qs = qs.filter(media_hashed_at__isnull=True)
    if limit:
        qs = qs[:limit]

    stats = MediaHashStats()
    for sub in qs:
        hashes = hash_submission_media(sub)
        stats.processed += 1
        if hashes:
            stats.with_media += 1
    return stats
