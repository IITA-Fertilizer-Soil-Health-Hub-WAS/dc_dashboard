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


@shared_task(name="ingestion.sync_use_case")
def sync_use_case_task(code: str) -> dict:
    uc = UseCase.objects.get(code=code)
    stats = sync_use_case(uc)
    run_for_use_case(uc)  # validate immediately after ingest
    return stats.as_dict()


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
    return stats.as_dict()


@shared_task(name="ingestion.sync_all_use_cases")
def sync_all_use_cases() -> list[dict]:
    results = []
    for uc in UseCase.objects.filter(is_active=True):
        results.append(sync_use_case(uc).as_dict())
        run_for_use_case(uc)
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
