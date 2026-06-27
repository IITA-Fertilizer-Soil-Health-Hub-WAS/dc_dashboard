"""Feature C, Stage C5: M&E exports (KPI summary + enumerators CSV, units GeoJSON)."""
from __future__ import annotations

import json
from datetime import date

import pytest
from django.urls import reverse

from apps.fieldwork.models import CollectionUnit
from apps.kpi.aggregate import rebuild_use_case_kpis
from apps.rbac.models import Role, UseCaseMembership
from apps.submissions.models import Enumerator, Submission
from apps.usecases.models import FormDefinition, Organization, UseCase

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    uc = UseCase.objects.create(code="PROJ-A", name="Project A", organization=org)
    UseCase.objects.create(code="PROJ-B", name="Project B", organization=org)
    form = FormDefinition.objects.create(use_case=uc, ona_form_id=3,
                                         role=FormDefinition.Role.VALIDATION)
    en = Enumerator.objects.create(use_case=uc, enid="EN-1", first_name="Ana")
    u1 = CollectionUnit.objects.create(use_case=uc, code="U1", name="Plot 1",
                                       lat="1.0", lon="2.0", country="RW")
    CollectionUnit.objects.create(use_case=uc, code="U2", lat="1.1", lon="2.1")
    for i in range(3):
        Submission.objects.create(use_case=uc, form=form, ona_uuid=f"a-{i}",
                                  content_hash="h", enumerator=en,
                                  collection_unit=u1, event_date=date.today())
    rebuild_use_case_kpis(uc)
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True,
                                                   organization=org)
    UseCaseMembership.objects.create(user=coord, use_case=uc, role=Role.TRIAL_COORDINATOR)
    return {"uc": uc, "coord": coord}


def test_kpi_summary_csv(client, world):
    client.force_login(world["coord"])
    resp = client.get(reverse("kpi:export", args=["PROJ-A", "kpi-summary"]))
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/csv")
    assert "attachment" in resp["Content-Disposition"]
    body = resp.content.decode()
    assert "submissions" in body
    assert ",3," in body or body.strip().endswith(",3")  # 3 submissions on the day


def test_enumerators_csv(client, world):
    client.force_login(world["coord"])
    resp = client.get(reverse("kpi:export", args=["PROJ-A", "enumerators"]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "EN-1" in body and "Ana" in body


def test_units_geojson(client, world):
    client.force_login(world["coord"])
    resp = client.get(reverse("kpi:export", args=["PROJ-A", "units-geojson"]))
    assert resp.status_code == 200
    assert "geojson" in resp["Content-Disposition"]
    fc = json.loads(resp.content)
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 2                      # both geo-located units
    collected = {f["properties"]["code"]: f["properties"]["collected"]
                 for f in fc["features"]}
    assert collected["U1"] is True and collected["U2"] is False
    # GeoJSON coordinates are [lon, lat].
    u1 = next(f for f in fc["features"] if f["properties"]["code"] == "U1")
    assert u1["geometry"]["coordinates"] == [2.0, 1.0]


def test_export_unknown_kind_404(client, world):
    client.force_login(world["coord"])
    assert client.get(reverse("kpi:export", args=["PROJ-A", "bogus"])).status_code == 404


def test_export_nonmember_404(client, world):
    client.force_login(world["coord"])
    assert client.get(
        reverse("kpi:export", args=["PROJ-B", "kpi-summary"])
    ).status_code == 404
