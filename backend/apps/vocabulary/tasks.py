"""Keep the Terminag vocabulary in sync with its GitHub repo (daily Celery Beat)."""
from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings

log = logging.getLogger(__name__)


@shared_task(name="vocabulary.sync_terminag")
def sync_terminag_task() -> dict:
    """Clone the configured Terminag repo and upsert it. Fail-soft — a clone or
    network error is logged, not raised, so a bad day doesn't crash Beat."""
    from .importer import VocabularySyncError, sync_from_repo

    repo = getattr(settings, "TERMINAG_REPO_URL", "")
    try:
        report = sync_from_repo(repo)
    except VocabularySyncError as exc:
        log.warning("Terminag sync failed: %s", exc)
        return {"ok": False, "error": str(exc)}
    log.info("Terminag synced: %s variables, %s values", report.variables, report.values)
    return {"ok": True, "variables": report.variables, "values": report.values}
