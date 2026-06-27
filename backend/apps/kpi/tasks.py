"""KPI aggregation tasks (Celery Beat ~15-min + webhook-triggered)."""
from __future__ import annotations

from celery import shared_task


@shared_task(name="kpi.rebuild_all")
def rebuild_all_kpis_task() -> dict:
    from .aggregate import rebuild_all_kpis

    return rebuild_all_kpis()


@shared_task(name="kpi.rebuild_use_case")
def rebuild_use_case_kpis_task(use_case_id: str) -> dict:
    from apps.usecases.models import UseCase

    from .aggregate import rebuild_use_case_kpis

    uc = UseCase.objects.filter(pk=use_case_id).first()
    return rebuild_use_case_kpis(uc) if uc else {}


@shared_task(name="kpi.run_alerts")
def run_alerts_task() -> dict:
    from .alerts import run_alerts

    return run_alerts()
