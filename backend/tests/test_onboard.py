"""Onboarding a new project to monitor — both the guided wizard and YAML import.

Reflects the ONA model: a project == a project; its forms == the entries.
"""
from __future__ import annotations

import pytest

from apps.console.onboarding import build_config, suggest_mappings, suggest_target
from apps.projects.models import Project

pytestmark = pytest.mark.django_db

YAML = """
project:
  code: NEW-PROJ
  name: New Project
  enid_patterns: ['^EN']
forms:
  - ona_form_id: 123456
    role: VALIDATION
    mappings:
      - {target: ENID, source: ['intro/enumerator_id'], transform: DIRECT}
      - {target: event_key, source: ['intro/event'], transform: DIRECT}
event_schedule:
  - {event_key: Event1, sequence: 1, anchor: SITE_SELECTION, offset_days: 14}
"""


@pytest.fixture
def staff(django_user_model):
    return django_user_model.objects.create_superuser("admin@x.org", "pw")


# ---- helpers ----
def test_suggest_target_heuristics():
    assert suggest_target("intro/enumerator_id") == "ENID"
    assert suggest_target("start/barcodehousehold") == "HHID"
    assert suggest_target("intro/event") == "event_key"
    assert suggest_target("planting/crop_cultivated") == "Crop"
    assert suggest_target("intro/household_geopoint") == "GEO"
    assert suggest_target("some/random_note") is None


def test_suggest_mappings_picks_first_match():
    fields = ["intro/enumerator_id", "intro/household_id", "intro/event", "meta/x"]
    chosen = suggest_mappings(fields)
    assert chosen["ENID"] == "intro/enumerator_id"
    assert chosen["HHID"] == "intro/household_id"
    assert chosen["event_key"] == "intro/event"


def test_build_config_assembles_full_project():
    post = {
        "code": "WZ", "name": "Wizard", "countries": "Rwanda", "crops": "maize",
        "enid_patterns": "^EN", "hhid_patterns": "^HH",
        "num_events": "2", "interval_days": "14",
        "form_count": "1", "form-0-id": "999", "form-0-role": "VALIDATION",
        "map-0-ENID": "intro/enumerator_id", "map-0-event_key": "intro/event",
    }
    cfg = build_config(post)
    assert cfg["project"]["code"] == "WZ"
    assert len(cfg["forms"]) == 1
    assert len(cfg["event_schedule"]) == 2
    assert any(r["code"] == "enid_pattern" for r in cfg["validation_rules"])


# ---- wizard (form-based) ----
def test_wizard_renders(client, staff):
    client.force_login(staff)
    resp = client.get("/manage/new-project/")
    assert resp.status_code == 200
    assert b"Onboard a project" in resp.content
    # Discovery is async: the page must NOT block on a network call.
    assert b"Discovering projects" in resp.content
    assert b'id="project-list"' in resp.content


def test_wizard_projects_partial_is_staff_only(client, django_user_model):
    user = django_user_model.objects.create_user("u@x.org", "pw", is_active=True)
    client.force_login(user)
    assert client.get("/manage/new-project/projects/").status_code == 403


def test_wizard_has_no_forced_role_dropdown(client, staff):
    # Onboarding must not force form classification — role is a hidden default.
    client.force_login(staff)
    html = client.get("/manage/new-project/").content.decode()
    assert 'name="form-IDX-role"' in html  # hidden default
    assert 'class="frole"' not in html     # no visible role <select>


def test_identities_derived_without_registration_form(django_user_model):
    """A project with only data forms (no registration form) still gets
    enumerators/units auto-created from the submission data."""
    from apps.fieldwork.models import CollectionUnit
    from apps.projects.models import FieldMapping, FormDefinition, Project
    from apps.submissions.models import Enumerator

    uc = Project.objects.create(code="AID", name="AID")
    form = FormDefinition.objects.create(project=uc, ona_form_id=1,
                                         role=FormDefinition.Role.VALIDATION)
    FieldMapping.objects.create(form=form, target_field="ENID", source_paths=["enid"])
    FieldMapping.objects.create(form=form, target_field="HHID", source_paths=["hhid"])

    class Fake:
        def get_data(self, fid):
            return [{"_uuid": "u1", "enid": "EN1", "hhid": "HH1"}]

    from apps.ingestion.sync import sync_project
    sync_project(uc, client=Fake())
    assert Enumerator.objects.filter(project=uc, enid="EN1").exists()
    hh = CollectionUnit.objects.get(project=uc, code="HH1")
    assert hh.enumerator.enid == "EN1"


def test_build_config_skips_unincluded_forms():
    from apps.console.onboarding import build_config
    # form 0 is a discovered row (present) but unticked -> skipped; form 1 included.
    cfg = build_config({
        "code": "X", "name": "X", "form_count": "2",
        "form-0-present": "1", "form-0-id": "100", "form-0-role": "VALIDATION",
        "form-1-present": "1", "form-1-include": "1", "form-1-id": "200",
        "form-1-role": "ENUM_REG",
    })
    ids = [f["ona_form_id"] for f in cfg["forms"]]
    assert ids == [200]  # only the included form


def test_wizard_onboards_forms_without_event_key(client, staff):
    # Multi-form projects (each form a stage) don't map event_key at onboarding;
    # validation must NOT block this — mappings are configured later.
    client.force_login(staff)
    post = {
        "code": "HUB-SL", "name": "Hub SL",
        "form_count": "2",
        "form-0-present": "1", "form-0-include": "1", "form-0-id": "885626",
        "form-1-present": "1", "form-1-include": "1", "form-1-id": "885629",
    }
    resp = client.post("/manage/new-project/", post)
    assert resp.status_code == 302  # onboarded, no event_key error
    uc = Project.objects.get(code="HUB-SL")
    assert uc.forms.count() == 2


def test_wizard_creates_project(client, staff):
    client.force_login(staff)
    post = {
        "code": "WZ-1", "name": "Wizard One", "enid_patterns": "^EN",
        "num_events": "1", "interval_days": "14",
        "form_count": "1", "form-0-id": "999", "form-0-role": "VALIDATION",
        "map-0-ENID": "intro/enumerator_id", "map-0-event_key": "intro/event",
    }
    resp = client.post("/manage/new-project/", post)
    assert resp.status_code == 302
    assert Project.objects.filter(code="WZ-1").exists()


def test_field_discovery_fallback_without_token(client, staff):
    client.force_login(staff)
    resp = client.post("/manage/new-project/fields/", {"index": "0", "form_id": "123"})
    assert resp.status_code == 200
    assert b"map-0-ENID" in resp.content  # mapping rows rendered


def test_wizard_non_staff_forbidden(client, django_user_model):
    user = django_user_model.objects.create_user("u@x.org", "pw", is_active=True)
    client.force_login(user)
    assert client.get("/manage/new-project/").status_code == 403


# ---- YAML import (advanced) ----
def test_yaml_import_creates_project(client, staff):
    client.force_login(staff)
    resp = client.post("/manage/new-project/advanced/", {"yaml": YAML})
    assert resp.status_code == 302
    uc = Project.objects.get(code="NEW-PROJ")
    assert uc.forms.count() == 1


def test_yaml_import_rejects_bad_config(client, staff):
    client.force_login(staff)
    resp = client.post("/manage/new-project/advanced/", {"yaml": "project:\n  name: x\n"})
    assert resp.status_code == 200
    assert not Project.objects.filter(name="x").exists()


def test_list_forms_parses_response(monkeypatch):
    from apps.ingestion import ona_client

    class FakeResp:
        status_code = 200

        def json(self):
            return [{"formid": 1, "title": "Reg", "num_of_submissions": 5,
                     "last_submission_time": "2026-01-01"}]

    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **k): return FakeResp()

    monkeypatch.setattr(ona_client.httpx, "Client", FakeClient)
    forms = ona_client.OnaClient(token="t").list_forms()
    assert forms[0]["formid"] == 1 and forms[0]["last_submission"] == "2026-01-01"
