"""Celery task for running the validation engine."""
from __future__ import annotations

from celery import shared_task

from apps.usecases.models import UseCase

from .engine import run_for_use_case


@shared_task(name="validation.run_for_use_case")
def run_validation_task(code: str) -> dict:
    uc = UseCase.objects.get(code=code)
    stats = run_for_use_case(uc)
    return {
        "use_case": stats.use_case,
        "opened": stats.opened,
        "resolved": stats.resolved,
        "flagged_submissions": stats.flagged_submissions,
    }
