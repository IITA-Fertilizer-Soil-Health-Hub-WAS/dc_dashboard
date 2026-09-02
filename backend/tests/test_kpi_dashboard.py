"""Feature C, Stage C2: KPI Overview + Project pages (role-scoped)."""
from __future__ import annotations

from datetime import date

import pytest
from django.urls import reverse

from apps.kpi.aggregate import rebuild_project_kpis
from apps.kpi.metrics import overview_metrics, project_metrics
from apps.projects.models import FormDefinition, Organization, Project
from apps.rbac.models import Membership, Role
from apps.submissions.models import Enumerator, Submission

pytestmark = pytest.mark.django_db


def _project(code, n, org=None):
    uc = Project.objects.create(code=code, name=code, organization=org)
    form = FormDefinition.objects.create(project=uc, ona_form_id=hash(code) % 100000,
                                         role=FormDefinition.Role.VALIDATION)
    en = Enumerator.objects.create(project=uc, enid=f"EN-{code}")
    for i in range(n):
        Submission.objects.create(project=uc, form=form, ona_uuid=f"{code}-{i}",
                                  content_hash="h", enumerator=en, event_date=date.today())
    rebuild_project_kpis(uc)
    return uc


@pytest.fixture
def world(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    a = _project("PROJ-A", 5, org)
    b = _project("PROJ-B", 2, org)
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True, organization=org)
    Membership.objects.create(user=coord, project=a, role=Role.TRIAL_COORDINATOR)
    admin = django_user_model.objects.create_superuser("a@x.org", "pw")
    return {"a": a, "b": b, "coord": coord, "admin": admin}


def test_overview_scoped_to_visible_projects(world):
    m = overview_metrics(world["coord"], "30")
    assert m["total_submissions"] == 5            # only PROJ-A
    assert m["active_projects"] == 1
    codes = {p["project__code"] for p in m["top_projects"]}
    assert codes == {"PROJ-A"}                     # PROJ-B not visible


def test_overview_admin_sees_all(world):
    m = overview_metrics(world["admin"], "30")
    assert m["total_submissions"] == 7             # 5 + 2
    assert m["active_projects"] == 2


def test_project_metrics(world):
    m = project_metrics(world["a"], "30")
    assert m["total_submissions"] == 5
    assert m["top_enumerators"][0]["n"] == 5
    assert m["forms"][0]["n"] == 5


def test_overview_view_renders(client, world):
    client.force_login(world["coord"])
    # kpi:overview now redirects to the single merged Overview page.
    resp = client.get(reverse("kpi:overview"), follow=True)
    assert resp.status_code == 200
    assert b"Overview" in resp.content
    assert b"PROJ-A" in resp.content
    assert b"PROJ-B" not in resp.content           # scoped


def test_project_view_member_ok_nonmember_404(client, world):
    client.force_login(world["coord"])
    assert client.get(reverse("kpi:project", args=["PROJ-A"])).status_code == 200
    assert client.get(reverse("kpi:project", args=["PROJ-B"])).status_code == 404


def test_period_filter(client, world):
    client.force_login(world["admin"])
    resp = client.get(reverse("kpi:overview") + "?days=7", follow=True)
    assert resp.status_code == 200
    assert b"Last 7 days" in resp.content
