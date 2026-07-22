"""Never fail silently: sync runs are recorded, failures alert, stale projects
are caught, and the System status page surfaces it all."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.ingestion import sync as syncmod
from apps.ingestion.models import SyncRun
from apps.projects.models import Organization, Project
from apps.rbac.models import Membership, Role

pytestmark = pytest.mark.django_db


@pytest.fixture
def project(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    p = Project.objects.create(code="P", name="P", organization=org)
    admin = django_user_model.objects.create_superuser("a@x.org", "pw")
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True,
                                                   organization=org)
    Membership.objects.create(user=coord, project=p, role=Role.TRIAL_COORDINATOR)
    return {"p": p, "admin": admin, "coord": coord}


def test_record_sync_success_logs_run(project, monkeypatch):
    p = project["p"]
    stats = syncmod.SyncStats(project=p.code, created=3, updated=1, unchanged=2)
    monkeypatch.setattr(syncmod, "sync_project", lambda proj, backend=None, client=None: stats)
    out = syncmod.record_sync(p, trigger="manual")
    run = SyncRun.objects.get(project=p)
    assert out is stats
    assert run.status == "OK" and run.created == 3 and run.updated == 1
    assert run.finished_at is not None


def test_record_sync_failure_records_and_alerts(project, monkeypatch):
    p = project["p"]
    sent = {}

    def boom(proj, backend=None, client=None):
        raise RuntimeError("collection server down")

    monkeypatch.setattr(syncmod, "sync_project", boom)
    monkeypatch.setattr("apps.common.email.send_safe_email",
                        lambda *a, **k: sent.update(called=True) or True)
    with pytest.raises(RuntimeError):
        syncmod.record_sync(p, trigger="scheduled")
    run = SyncRun.objects.get(project=p)
    assert run.status == "ERROR" and "collection server down" in run.message
    assert sent.get("called")  # admins were alerted


def test_check_stale_projects_alerts(project, monkeypatch):
    from apps.ingestion.tasks import check_stale_projects
    sent = {}
    monkeypatch.setattr("apps.common.email.send_safe_email",
                        lambda *a, **k: sent.update(called=True) or True)
    # The project has no submissions at all → stale.
    stale = check_stale_projects(days=3)
    assert project["p"].code in stale and sent.get("called")


def test_system_status_page(client, project):
    SyncRun.objects.create(project=project["p"], status="ERROR", message="boom")
    client.force_login(project["admin"])
    resp = client.get(reverse("console:system_status"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "System status" in body and project["p"].code in body
    # Coordinators (non-staff) can't see the operational page.
    client.force_login(project["coord"])
    assert client.get(reverse("console:system_status")).status_code == 403


def test_beat_schedule_task_name_is_valid():
    """The daily sync must point at a task that actually exists (it used to
    reference ingestion.sync_all_use_cases, which is unregistered → silent)."""
    from django.conf import settings

    task = settings.CELERY_BEAT_SCHEDULE["daily-source-sync"]["task"]
    assert task == "ingestion.sync_all_projects"
