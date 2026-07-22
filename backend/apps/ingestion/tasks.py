"""Celery tasks for scheduled + on-demand ingestion.

Replaces the R daily cron (`Rscript dataprocessing.R`). `sync_all_projects` is
wired to Celery Beat (daily); `sync_project_task` backs the Admin "Sync now"
button. Validation is enqueued per project once the engine lands in Phase 6.
"""
from __future__ import annotations

from celery import shared_task

from apps.projects.models import Project
from apps.validation.engine import run_for_project

from .sync import record_sync, sync_project

# Cap on media fetched per run — hashing is network-bound, so we bound each pass
# and let the recurring task drain the backlog over subsequent runs.
MEDIA_HASH_BATCH = 300


@shared_task(name="ingestion.sync_project")
def sync_project_task(code: str, trigger: str = "manual") -> dict:
    uc = Project.objects.get(code=code)
    stats = record_sync(uc, trigger=trigger)  # records a SyncRun; alerts on failure
    run_for_project(uc)  # validate immediately after ingest
    hash_media_task.delay(code)  # hash new media off the ingest path
    _refresh_schemas(uc)  # keep form names + field lists current for the builder
    return stats.as_dict()


def _refresh_schemas(project) -> None:
    """Best-effort refresh of each form's name + field schema, so the validation
    rule builder always has the full field list without a manual import."""
    try:
        from apps.ingestion.form_schema import sync_project_schemas
        sync_project_schemas(project)
    except Exception:
        pass


@shared_task(name="ingestion.hash_media")
def hash_media_task(code: str, limit: int = MEDIA_HASH_BATCH) -> dict:
    """Hash newly-ingested media, then re-validate so PHOTO_REUSE reflects the fresh
    hashes. Runs after ingest and on Beat, so the reused-photo check stays current
    without a manual `hash_media` run. Idempotent via `media_hashed_at`."""
    from .media_hash import hash_project_media

    uc = Project.objects.filter(code=code).first()
    if uc is None:
        return {"code": code, "status": "unknown_project"}
    stats = hash_project_media(uc, limit=limit, only_new=True)
    if stats.with_media:
        run_for_project(uc)  # surface any new PHOTO_REUSE flags
    return {"code": code, "processed": stats.processed, "with_media": stats.with_media}


@shared_task(name="ingestion.webhook_ingest")
def webhook_ingest_task(code: str) -> dict:
    """Triggered by a collection-server webhook: re-pull the project, validate,
    then refresh its M&E aggregates so the real-time cards update at once.

    We re-pull rather than trust the webhook body — keeps it server-agnostic and
    reuses the idempotent ingest (no duplicates on repeated hits)."""
    from apps.kpi.aggregate import rebuild_project_kpis

    uc = Project.objects.filter(code=code).first()
    if uc is None:
        return {"code": code, "status": "unknown_project"}
    stats = record_sync(uc, trigger="webhook")
    run_for_project(uc)
    rebuild_project_kpis(uc)
    hash_media_task.delay(code)
    return stats.as_dict()


@shared_task(name="ingestion.sync_all_projects")
def sync_all_projects() -> list[dict]:
    results = []
    for uc in Project.objects.filter(is_active=True):
        # A failure on one project is recorded + alerted, and must not stop the rest.
        try:
            stats = record_sync(uc, trigger="scheduled")
            run_for_project(uc)
            hash_media_task.delay(uc.code)
            results.append(stats.as_dict())
        except Exception as exc:  # already recorded + alerted in record_sync
            results.append({"project": uc.code, "error": str(exc)[:200]})
    return results


@shared_task(name="ingestion.check_stale_projects")
def check_stale_projects(days: int = 3) -> list[str]:
    """Flag active projects with no submission in `days` days — a silent-failure
    tripwire: a sync can 'succeed' yet a form/device problem means nothing new
    arrives. Alerts the platform admins with the stale list."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.accounts.models import User
    from apps.common.email import send_safe_email
    from apps.submissions.models import Submission

    cutoff = timezone.now() - timedelta(days=days)
    stale = []
    for uc in Project.objects.filter(is_active=True):
        last = (Submission.objects.filter(project=uc).order_by("-ingested_at")
                .values_list("ingested_at", flat=True).first())
        if last is None or last < cutoff:
            stale.append(uc)
    if stale:
        admins = list(User.objects.filter(is_superuser=True, is_active=True)
                      .exclude(email="").values_list("email", flat=True))
        lines = "\n".join(f"  - {p.code} ({p.name})" for p in stale)
        send_safe_email(
            f"[Fieldbase] {len(stale)} project(s) with no data in {days} days",
            f"No new submissions in the last {days} days for:\n\n{lines}\n\n"
            f"Check the collection server, the forms, and the field teams.",
            admins, context="stale-projects")
    return [p.code for p in stale]


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
