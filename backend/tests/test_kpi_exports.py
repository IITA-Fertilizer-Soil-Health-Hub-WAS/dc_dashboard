"""Feature C, Stage C5: M&E exports (KPI summary + enumerators CSV, units GeoJSON)."""
from __future__ import annotations

import json
from datetime import date

import pytest
from django.urls import reverse

from apps.fieldwork.models import CollectionUnit
from apps.kpi.aggregate import rebuild_project_kpis
from apps.projects.models import FormDefinition, Organization, Project
from apps.rbac.models import Role, UseCaseMembership
from apps.submissions.models import Enumerator, Submission

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    uc = Project.objects.create(code="PROJ-A", name="Project A", organization=org)
    Project.objects.create(code="PROJ-B", name="Project B", organization=org)
    form = FormDefinition.objects.create(project=uc, ona_form_id=3,
                                         role=FormDefinition.Role.VALIDATION)
    en = Enumerator.objects.create(project=uc, enid="EN-1", first_name="Ana")
    u1 = CollectionUnit.objects.create(project=uc, code="U1", name="Plot 1",
                                       lat="1.0", lon="2.0", country="RW")
    CollectionUnit.objects.create(project=uc, code="U2", lat="1.1", lon="2.1")
    for i in range(3):
        Submission.objects.create(project=uc, form=form, ona_uuid=f"a-{i}",
                                  content_hash="h", enumerator=en,
                                  collection_unit=u1, event_date=date.today())
    rebuild_project_kpis(uc)
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True,
                                                   organization=org)
    UseCaseMembership.objects.create(user=coord, project=uc, role=Role.TRIAL_COORDINATOR)
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


# --- Stage C5b: XLSX + STATA/SPSS formats and the approved dataset -----------

def test_kpi_summary_xlsx(client, world):
    client.force_login(world["coord"])
    resp = client.get(reverse("kpi:export", args=["PROJ-A", "kpi-summary"]) + "?fmt=xlsx")
    assert resp.status_code == 200
    assert "spreadsheetml" in resp["Content-Type"]
    assert resp.content[:2] == b"PK"            # xlsx is a zip
    assert resp["Content-Disposition"].endswith('.xlsx"')


def test_enumerators_xlsx(client, world):
    client.force_login(world["coord"])
    resp = client.get(reverse("kpi:export", args=["PROJ-A", "enumerators"]) + "?fmt=xlsx")
    assert resp.status_code == 200
    assert resp.content[:2] == b"PK"


def test_approved_dataset_csv(client, world):
    client.force_login(world["coord"])
    resp = client.get(reverse("kpi:export", args=["PROJ-A", "approved"]))
    assert resp.status_code == 200
    assert "ona_uuid" in resp.content.decode()


def test_stata_export(client, world):
    pytest.importorskip("pyreadstat")
    client.force_login(world["coord"])
    resp = client.get(reverse("kpi:export", args=["PROJ-A", "kpi-summary"]) + "?fmt=dta")
    assert resp.status_code == 200
    assert resp["Content-Disposition"].endswith('.dta"')
    assert len(resp.content) > 0


def test_spss_export(client, world):
    pytest.importorskip("pyreadstat")
    client.force_login(world["coord"])
    resp = client.get(reverse("kpi:export", args=["PROJ-A", "enumerators"]) + "?fmt=sav")
    assert resp.status_code == 200
    assert resp["Content-Disposition"].endswith('.sav"')
    assert len(resp.content) > 0


def test_unknown_format_404(client, world):
    client.force_login(world["coord"])
    assert client.get(
        reverse("kpi:export", args=["PROJ-A", "kpi-summary"]) + "?fmt=bogus"
    ).status_code == 404


def test_sanitize_columns_makes_valid_stata_names():
    from apps.kpi.exports import _sanitize_columns
    out = _sanitize_columns(["ona_uuid", "grp/field.name", "123start", "dup", "dup"])
    # All start with a letter and are alnum/underscore only.
    assert all(c[0].isalpha() for c in out)
    assert all(all(ch.isalnum() or ch == "_" for ch in c) for c in out)
    # Duplicates are disambiguated.
    assert len(set(out)) == len(out)
