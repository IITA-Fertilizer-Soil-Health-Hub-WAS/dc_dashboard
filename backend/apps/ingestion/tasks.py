"""Celery tasks for scheduled + on-demand ingestion.

Replaces the R daily cron (`Rscript dataprocessing.R`). `sync_all_use_cases` is
wired to Celery Beat (daily); `sync_use_case_task` backs the Admin "Sync now"
button. Validation is enqueued per use case once the engine lands in Phase 6.
"""
from __future__ import annotations

from celery import shared_task

from apps.usecases.models import UseCase
from apps.validation.engine import run_for_use_case

from .sync import sync_use_case

# Cap on media fetched per run — hashing is network-bound, so we bound each pass
# and let the recurring task drain the backlog over subsequent runs.
MEDIA_HASH_BATCH = 300


@shared_task(name="ingestion.sync_use_case")
def sync_use_case_task(code: str) -> dict:
    uc = UseCase.objects.get(code=code)
    stats = sync_use_case(uc)
    run_for_use_case(uc)  # validate immediately after ingest
    hash_media_task.delay(code)  # hash new media off the ingest path
    return stats.as_dict()


@shared_task(name="ingestion.hash_media")
def hash_media_task(code: str, limit: int = MEDIA_HASH_BATCH) -> dict:
    """Hash newly-ingested media, then re-validate so PHOTO_REUSE reflects the fresh
    hashes. Runs after ingest and on Beat, so the reused-photo check stays current
    without a manual `hash_media` run. Idempotent via `media_hashed_at`."""
    from .media_hash import hash_use_case_media

    uc = UseCase.objects.filter(code=code).first()
    if uc is None:
        return {"code": code, "status": "unknown_use_case"}
    stats = hash_use_case_media(uc, limit=limit, only_new=True)
    if stats.with_media:
        run_for_use_case(uc)  # surface any new PHOTO_REUSE flags
    return {"code": code, "processed": stats.processed, "with_media": stats.with_media}


@shared_task(name="ingestion.webhook_ingest")
def webhook_ingest_task(code: str) -> dict:
    """Triggered by a collection-server webhook: re-pull the project, validate,
    then refresh its M&E aggregates so the real-time cards update at once.

    We re-pull rather than trust the webhook body — keeps it server-agnostic and
    reuses the idempotent ingest (no duplicates on repeated hits)."""
    from apps.kpi.aggregate import rebuild_use_case_kpis

    uc = UseCase.objects.filter(code=code).first()
    if uc is None:
        return {"code": code, "status": "unknown_use_case"}
    stats = sync_use_case(uc)
    run_for_use_case(uc)
    rebuild_use_case_kpis(uc)
    hash_media_task.delay(code)
    return stats.as_dict()


@shared_task(name="ingestion.sync_all_use_cases")
def sync_all_use_cases() -> list[dict]:
    results = []
    for uc in UseCase.objects.filter(is_active=True):
        results.append(sync_use_case(uc).as_dict())
        run_for_use_case(uc)
        hash_media_task.delay(uc.code)  # background media hashing per project
    return results


@shared_task(name="ingestion.writeback_submission")
def writeback_submission_task(submission_id: str) -> str:
    """Propagate a submission's reviewer edits to its source server."""
    from apps.submissions.models import Submission

    from .writeback import push_submission

    submission = Submission.objects.filter(pk=submission_id).first()
    if submission is None:
        return "missing"
    push_submission(submission)
    return submission.writeback_status
