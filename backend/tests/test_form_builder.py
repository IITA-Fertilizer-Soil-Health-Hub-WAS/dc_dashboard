"""In-app form builder: save a draft (with vocabulary check) and publish it."""
from __future__ import annotations

import json

import pytest
from django.urls import reverse

from apps.ingestion.backends.base import PublishResult
from apps.projects.models import (
    Country,
    FormDefinition,
    FormDraft,
    Organization,
    Project,
    Region,
)
from apps.rbac.models import Membership, Role
from apps.vocabulary.models import VocabularyVariable

pytestmark = pytest.mark.django_db


@pytest.fixture
def coord(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    region = Region.objects.create(organization=org, code="EA", name="EA")
    country = Country.objects.create(region=region, code="RW", name="Rwanda")
    proj = Project.objects.create(code="MINE", name="Mine", organization=org, country=country)
    u = django_user_model.objects.create_user("rc@x.org", "pw", is_active=True, organization=org)
    Membership.objects.create(user=u, region=region, role=Role.REGIONAL_COORDINATOR)
    # A vocabulary term so the missing-terms check has something to match.
    VocabularyVariable.objects.create(name="crop", category="crop", data_type="character")
    return {"user": u, "proj": proj}


SPEC = {
    "settings": {"form_title": "Baseline"},
    "questions": [
        {"type": "text", "name": "farmer", "label": "Farmer"},
        {"type": "select_one", "name": "crop", "label": "Crop", "list": "crop"},
    ],
    "choices": {"crop": [{"name": "maize", "label": "Maize"}]},
}


def test_save_draft_records_missing_terms(client, coord):
    client.force_login(coord["user"])
    resp = client.post(reverse("console:form_new"), {
        "title": "Baseline", "project": str(coord["proj"].pk),
        "role": "VALIDATION", "action": "save", "spec": json.dumps(SPEC),
    })
    assert resp.status_code == 302
    draft = FormDraft.objects.get(title="Baseline")
    assert draft.project == coord["proj"] and draft.created_by == coord["user"]
    # 'crop' is in the vocabulary; 'farmer' is not → reported missing.
    assert draft.missing_terms == ["farmer"]


def test_invalid_spec_rejected(client, coord):
    client.force_login(coord["user"])
    bad = {"questions": [{"type": "select_one", "name": "crop", "label": "Crop"}]}  # no list
    resp = client.post(reverse("console:form_new"), {
        "title": "Bad", "project": str(coord["proj"].pk), "action": "save",
        "spec": json.dumps(bad),
    })
    assert resp.status_code == 200
    assert b"isn&#x27;t valid" in resp.content or b"isn't valid" in resp.content
    assert not FormDraft.objects.filter(title="Bad").exists()


def test_publish_draft_generates_and_pushes(client, coord, monkeypatch):
    backend_calls = {}

    def fake_publish(project, xlsx, **kw):
        backend_calls["xlsx_len"] = len(xlsx)
        form = FormDefinition.objects.create(project=project, server_form_id="baseline_v1",
                                             role=FormDefinition.Role.VALIDATION)
        return form, PublishResult(ok=True, server_form_id="baseline_v1", title="Baseline")

    monkeypatch.setattr("apps.ingestion.publishing.publish_xlsform", fake_publish)

    draft = FormDraft.objects.create(project=coord["proj"], title="Baseline", spec=SPEC,
                                     created_by=coord["user"])
    client.force_login(coord["user"])
    resp = client.post(reverse("console:form_publish_draft", args=[draft.pk]))
    assert resp.status_code == 302
    draft.refresh_from_db()
    assert draft.status == FormDraft.Status.PUBLISHED
    assert draft.published_form is not None
    assert backend_calls["xlsx_len"] > 0  # a real XLSForm was generated + pushed


def test_builder_blocked_for_plain_member(client, django_user_model):
    u = django_user_model.objects.create_user("v@x.org", "pw", is_active=True)
    client.force_login(u)
    assert client.get(reverse("console:form_builder")).status_code == 403


def test_draft_scoped_to_own_projects(client, coord, django_user_model):
    other = Project.objects.create(code="OTHER", name="Other")
    draft = FormDraft.objects.create(project=other, title="Theirs", spec=SPEC)
    client.force_login(coord["user"])
    # Editing a draft outside the coordinator's scope 404s.
    assert client.get(reverse("console:form_edit", args=[draft.pk])).status_code == 404
