"""Celery task for running the validation engine."""
from __future__ import annotations

from celery import shared_task

from apps.projects.models import Project

from .engine import run_for_project


@shared_task(name="validation.run_for_project")
def run_validation_task(code: str) -> dict:
    uc = Project.objects.get(code=code)
    stats = run_for_project(uc)
    return {
        "project": stats.project,
        "opened": stats.opened,
        "resolved": stats.resolved,
        "flagged_submissions": stats.flagged_submissions,
    }
