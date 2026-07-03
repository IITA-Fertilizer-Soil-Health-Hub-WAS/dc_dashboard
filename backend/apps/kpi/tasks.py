"""KPI aggregation tasks (Celery Beat ~15-min + webhook-triggered)."""
from __future__ import annotations

from celery import shared_task


@shared_task(name="kpi.rebuild_all")
def rebuild_all_kpis_task() -> dict:
    from .aggregate import rebuild_all_kpis

    return rebuild_all_kpis()


@shared_task(name="kpi.rebuild_project")
def rebuild_project_kpis_task(project_id: str) -> dict:
    from apps.projects.models import Project

    from .aggregate import rebuild_project_kpis

    uc = Project.objects.filter(pk=project_id).first()
    return rebuild_project_kpis(uc) if uc else {}


@shared_task(name="kpi.run_alerts")
def run_alerts_task() -> dict:
    from .alerts import run_alerts

    return run_alerts()
