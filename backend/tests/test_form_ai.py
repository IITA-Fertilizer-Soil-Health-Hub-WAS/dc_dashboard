"""Tier 3: protocol → draft form via AI (gated, human-in-the-loop)."""
from __future__ import annotations

import io
import json
import zipfile

import pytest
from django.urls import reverse

from apps.ingestion import form_ai
from apps.ingestion.protocol_text import ProtocolError, extract_text
from apps.projects.models import (
    Country,
    FormDraft,
    Organization,
    Project,
    Region,
)
from apps.rbac.models import Membership, Role

pytestmark = pytest.mark.django_db


# --- text extraction (no network) -------------------------------------------
def test_extract_plain_text():
    assert extract_text("p.txt", b"How many plots?\nCrop grown?") == "How many plots?\nCrop grown?"


def test_extract_docx():
    xml = ('<w:document xmlns:w="x"><w:body>'
           '<w:p><w:r><w:t>Farmer name</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>Crop </w:t></w:r><w:r><w:t>grown</w:t></w:r></w:p>'
           '</w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    text = extract_text("protocol.docx", buf.getvalue())
    assert "Farmer name" in text and "Crop grown" in text


def test_extract_pdf_rejected():
    with pytest.raises(ProtocolError):
        extract_text("p.pdf", b"%PDF-1.7 ...")


# --- draft_spec (gating + parsing) ------------------------------------------
def test_draft_spec_gated_off(settings):
    settings.FORM_AI_ENABLED = False
    with pytest.raises(form_ai.FormAIError):
        form_ai.draft_spec("some protocol")


def test_check_disabled(settings):
    settings.FORM_AI_ENABLED = False
    result = form_ai.check()
    assert result["ok"] is False and "Disabled" in result["message"]


def test_check_ok(monkeypatch, settings):
    settings.FORM_AI_ENABLED = True
    settings.FORM_AI_API_KEY = "test-key"
    _mock_anthropic(monkeypatch, 200, "ok")
    result = form_ai.check()
    assert result["ok"] is True and result["model"]


def _mock_anthropic(monkeypatch, status, text):
    class Resp:
        status_code = status
        def json(self):  # noqa: E301
            return {"content": [{"type": "text", "text": text}]}
        @property
        def text(self):  # noqa: E301
            return text

    class Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, *a, **k): return Resp()

    monkeypatch.setattr(form_ai.httpx, "Client", Client)


def test_draft_spec_parses_json(monkeypatch, settings):
    settings.FORM_AI_ENABLED = True
    settings.FORM_AI_API_KEY = "test-key"
    spec = {"questions": [{"type": "text", "name": "farmer", "label": "Farmer"}]}
    # The model may wrap output in a ```json fence — the parser strips it.
    _mock_anthropic(monkeypatch, 200, "```json\n" + json.dumps(spec) + "\n```")
    out = form_ai.draft_spec("How is the farmer identified?")
    assert out["questions"][0]["name"] == "farmer"


def test_draft_spec_bad_json_raises(monkeypatch, settings):
    settings.FORM_AI_ENABLED = True
    settings.FORM_AI_API_KEY = "test-key"
    _mock_anthropic(monkeypatch, 200, "sorry, I can't do that")
    with pytest.raises(form_ai.FormAIError):
        form_ai.draft_spec("x")


# --- view -------------------------------------------------------------------
@pytest.fixture
def coord(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    region = Region.objects.create(organization=org, code="EA", name="EA")
    country = Country.objects.create(region=region, code="RW", name="Rwanda")
    proj = Project.objects.create(code="MINE", name="Mine", organization=org, country=country)
    u = django_user_model.objects.create_user("rc@x.org", "pw", is_active=True, organization=org)
    Membership.objects.create(user=u, region=region, role=Role.REGIONAL_COORDINATOR)
    return {"user": u, "proj": proj}


def test_ai_view_creates_draft(client, coord, monkeypatch):
    spec = {"questions": [
        {"type": "text", "name": "farmer", "label": "Farmer"},
        {"type": "select_one", "name": "crop", "label": "Crop", "list": "crop"},
    ], "choices": {"crop": [{"name": "maize", "label": "Maize"}]}}
    monkeypatch.setattr("apps.ingestion.form_ai.draft_spec", lambda text: dict(spec))
    client.force_login(coord["user"])
    resp = client.post(reverse("console:form_ai"), {
        "title": "Baseline", "project": str(coord["proj"].pk),
        "protocol_text": "A protocol describing farmer and crop questions.",
    })
    assert resp.status_code == 302
    draft = FormDraft.objects.get(title="Baseline")
    assert draft.source == FormDraft.Source.AI
    assert draft.created_by == coord["user"]
    # 'farmer' and 'crop' aren't in the (empty test) vocabulary → both reported.
    assert set(draft.missing_terms) == {"farmer", "crop"}


def test_ai_view_surfaces_failure(client, coord, monkeypatch):
    def boom(text):
        raise form_ai.FormAIError("AI service error (HTTP 401): bad key")
    monkeypatch.setattr("apps.ingestion.form_ai.draft_spec", boom)
    client.force_login(coord["user"])
    resp = client.post(reverse("console:form_ai"), {
        "title": "X", "project": str(coord["proj"].pk), "protocol_text": "text",
    })
    assert resp.status_code == 200
    assert b"HTTP 401" in resp.content
    assert not FormDraft.objects.filter(title="X").exists()


def test_ai_view_blocked_for_plain_member(client, django_user_model):
    u = django_user_model.objects.create_user("v@x.org", "pw", is_active=True)
    client.force_login(u)
    assert client.get(reverse("console:form_ai")).status_code == 403
