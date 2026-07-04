"""Self-serve analytics dashboard builder: build widgets, compute, save, view."""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from django.urls import reverse

from apps.kpi.builder import compute_widget
from apps.kpi.models import Dashboard, EnumeratorKpiDaily, ProjectKpiDaily
from apps.projects.models import Organization, Project
from apps.rbac.models import Membership, Role
from apps.submissions.models import Enumerator

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    p = Project.objects.create(code="P1", name="P1", organization=org)
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True, organization=org)
    Membership.objects.create(user=coord, project=p, role=Role.TRIAL_COORDINATOR)
    # A few days of aggregates to compute over.
    today = date.today()
    for i, n in enumerate([3, 5, 2, 8]):
        ProjectKpiDaily.objects.create(project=p, date=today - timedelta(days=i), submissions=n)
    en = Enumerator.objects.create(project=p, enid="EN1")
    EnumeratorKpiDaily.objects.create(project=p, enumerator=en, date=today, submissions=8)
    return {"org": org, "p": p, "coord": coord}


def test_compute_number_metric(world):
    w = compute_widget({"metric": "submissions_total", "period": "30"}, [world["p"].id])
    assert w["data"]["kind"] == "number" and w["data"]["value"] == 18


def test_compute_series_metric(world):
    w = compute_widget({"metric": "submissions", "chart": "line", "period": "30"}, [world["p"].id])
    assert w["data"]["kind"] == "series" and len(w["data"]["points"]) == 4
    assert w["series_max"] == 8 and "<svg" in w["spark_svg"]


def test_compute_table_metric(world):
    w = compute_widget({"metric": "top_enumerators", "chart": "table"}, [world["p"].id])
    assert w["data"]["kind"] == "rows" and ["EN1", 8] in w["data"]["rows"]


def test_unknown_metric_degrades(world):
    w = compute_widget({"metric": "nope"}, [world["p"].id])
    assert w["data"]["kind"] == "number" and w["data"]["value"] == 0


def test_save_and_view_dashboard(client, world):
    client.force_login(world["coord"])
    widgets = [{"title": "Total", "metric": "submissions_total", "chart": "number", "period": "30"},
               {"title": "", "metric": "submissions", "chart": "bar", "period": "7"}]
    resp = client.post(reverse("kpi:dashboard_new"),
                       {"name": "My board", "project": "", "widgets": json.dumps(widgets)})
    assert resp.status_code == 302
    dash = Dashboard.objects.get(name="My board")
    assert dash.owner == world["coord"] and len(dash.widgets) == 2
    # View renders the computed widgets.
    view = client.get(reverse("kpi:dashboard_view", args=[dash.pk]))
    assert view.status_code == 200 and b"Total" in view.content


def test_shared_dashboard_visible_to_org(client, world, django_user_model):
    other = django_user_model.objects.create_user("o2@x.org", "pw", is_active=True,
                                                   organization=world["org"])
    Membership.objects.create(user=other, project=world["p"], role=Role.VIEWER)
    dash = Dashboard.objects.create(owner=world["coord"], name="Shared", shared=True,
                                    widgets=[{"metric": "submissions_total", "chart": "number"}])
    client.force_login(other)
    assert client.get(reverse("kpi:dashboards")).content.count(b"Shared") >= 1
    assert client.get(reverse("kpi:dashboard_view", args=[dash.pk])).status_code == 200


def test_private_dashboard_hidden_from_others(client, world, django_user_model):
    stranger = django_user_model.objects.create_user("s@x.org", "pw", is_active=True)
    dash = Dashboard.objects.create(owner=world["coord"], name="Private", shared=False, widgets=[])
    client.force_login(stranger)
    assert client.get(reverse("kpi:dashboard_view", args=[dash.pk])).status_code == 404


def test_only_owner_can_edit(client, world, django_user_model):
    other = django_user_model.objects.create_user("o2@x.org", "pw", is_active=True,
                                                   organization=world["org"])
    dash = Dashboard.objects.create(owner=world["coord"], name="Board", shared=True, widgets=[])
    client.force_login(other)
    assert client.get(reverse("kpi:dashboard_edit", args=[dash.pk])).status_code == 404


def test_care_widgets(django_user_model):
    """Care coverage + defaulters are available as dashboard widgets."""
    from datetime import date, timedelta

    from apps.care.models import CareProgram
    from apps.fieldwork.models import CollectionUnit
    from apps.kpi.builder import METRICS, compute_widget
    from apps.projects.models import EventScheduleItem, FormDefinition, Organization, Project
    from apps.submissions.models import Submission

    assert "care_coverage" in METRICS and "care_defaulters" in METRICS

    org = Organization.objects.create(code="o", name="O")
    p = Project.objects.create(code="CP", name="CP", organization=org)
    CareProgram.objects.create(project=p, client_label="Farmer")
    EventScheduleItem.objects.create(project=p, event_key="Event1", sequence=1,
                                     anchor="SITE_SELECTION", offset_days=14, grace_days=3)
    EventScheduleItem.objects.create(project=p, event_key="Event2", sequence=2,
                                     anchor="SITE_SELECTION", offset_days=45, grace_days=3)
    form = FormDefinition.objects.create(project=p, ona_form_id=1,
                                         role=FormDefinition.Role.VALIDATION)
    anchor = date.today() - timedelta(days=60)
    u = CollectionUnit.objects.create(project=p, code="U1", site_selection_date=anchor)
    Submission.objects.create(project=p, form=form, collection_unit=u, event_key="Event1",
                              event_date=anchor + timedelta(days=14), ona_uuid="x", content_hash="h")
    # 1 of 2 visits done -> 50%; Event2 overdue -> 1 defaulter.
    cov = compute_widget({"metric": "care_coverage"}, [p.id])
    assert cov["data"]["value"] == 50 and cov["data"]["suffix"] == "%"
    dfl = compute_widget({"metric": "care_defaulters"}, [p.id])
    assert dfl["data"]["value"] == 1
