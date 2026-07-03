"""SDMT-inspired #2: photos/media in the review screen."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.ingestion.attachments import parse_attachments
from apps.projects.models import FormDefinition, Organization, Project
from apps.rbac.models import Role, UseCaseMembership
from apps.submissions.models import Submission

pytestmark = pytest.mark.django_db


PAYLOAD = {
    "plot_photo": "field_9182.jpg",
    "notes": "looks good",
    "_attachments": [
        {"id": 501, "name": "field_9182.jpg", "filename": "u/attachments/x/field_9182.jpg",
         "mimetype": "image/jpeg"},
        {"id": 502, "filename": "u/attachments/x/voice_1.mp3", "mimetype": "audio/mp3"},
    ],
}


def test_parse_attachments_links_question_and_flags_images():
    atts = parse_attachments(PAYLOAD)
    by_id = {a["id"]: a for a in atts}
    assert by_id[501]["is_image"] is True
    assert by_id[501]["question"] == "plot_photo"
    assert by_id[502]["is_image"] is False
    assert by_id[502]["name"] == "voice_1.mp3"  # basename from filename


def test_parse_attachments_empty():
    assert parse_attachments({}) == []
    assert parse_attachments({"_attachments": "bad"}) == []


@pytest.fixture
def world(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    uc = Project.objects.create(code="PROJ-A", name="A", organization=org)
    form = FormDefinition.objects.create(project=uc, ona_form_id=1, role=FormDefinition.Role.VALIDATION)
    sub = Submission.objects.create(project=uc, form=form, ona_uuid="m1",
                                    content_hash="h", raw_payload=PAYLOAD)
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True, organization=org)
    UseCaseMembership.objects.create(user=coord, project=uc, role=Role.TRIAL_COORDINATOR)
    return {"uc": uc, "sub": sub, "coord": coord}


def test_review_screen_shows_media_gallery(client, world):
    client.force_login(world["coord"])
    url = reverse("dashboards:submission_review", args=["PROJ-A", world["sub"].id])
    page = client.get(url).content
    media_url = reverse("dashboards:submission_media",
                        args=["PROJ-A", world["sub"].id, "field_9182.jpg"])
    assert media_url.encode() in page  # image proxied through the app
    assert b"voice_1.mp3" in page


def test_media_proxy_streams_and_scopes(client, world, monkeypatch):
    from apps.ingestion.backends.base import CollectionBackend

    class StubBackend(CollectionBackend):
        def fetch_attachment(self, attachment):
            return b"JPEGBYTES", "image/jpeg"

    monkeypatch.setattr("apps.ingestion.backends.registry.get_backend_for",
                        lambda uc: StubBackend())
    client.force_login(world["coord"])
    ok = reverse("dashboards:submission_media",
                 args=["PROJ-A", world["sub"].id, "field_9182.jpg"])
    resp = client.get(ok)
    assert resp.status_code == 200 and resp["Content-Type"] == "image/jpeg"
    assert resp.content == b"JPEGBYTES"
    # A filename not on this submission's record is rejected.
    bad = reverse("dashboards:submission_media",
                  args=["PROJ-A", world["sub"].id, "nope.jpg"])
    assert client.get(bad).status_code == 404


# --- backend coverage: Kobo (embedded) + ODK Central (lookup) ---

class _Resp:
    def __init__(self, content=b"", ctype="image/jpeg", status=200, json=None):
        self.content, self.status_code = content, status
        self.headers = {"Content-Type": ctype}
        self._json = json or []
        self.text = ""

    def json(self):
        return self._json


class _HttpxStub:
    """Minimal httpx.Client stand-in: records the URL, returns a canned response."""
    def __init__(self, resp):
        self.resp, self.url = resp, None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, headers=None, params=None):
        self.url = url
        return self.resp


def test_kobo_fetch_uses_download_url(monkeypatch):
    from apps.ingestion.backends import kobo

    stub = _HttpxStub(_Resp(content=b"KOBOIMG", ctype="image/png"))
    monkeypatch.setattr(kobo.httpx, "Client", lambda *a, **k: stub)
    backend = kobo.KoboBackend(token="t")
    data, ctype = backend.fetch_attachment(
        {"name": "p.png", "download_url": "https://kc.kobo/media/p.png"})
    assert data == b"KOBOIMG" and ctype == "image/png"
    assert stub.url == "https://kc.kobo/media/p.png"


class _SubStub:
    def __init__(self, payload, form_ref):
        self.raw_payload = payload
        self.ona_uuid = payload.get("__id", "")
        self.form = type("F", (), {"server_ref": form_ref})()


def test_odk_central_lists_and_fetches_by_name(monkeypatch):
    from apps.ingestion.backends import odkcentral

    backend = odkcentral.OdkCentralBackend(base_url="https://c.example", token="t",
                                           config={"project_id": 7})
    # list_attachments → uses the per-submission attachments endpoint
    monkeypatch.setattr(backend, "_get_json",
                        lambda path: [{"name": "shot.jpg", "exists": True}])
    sub = _SubStub({"__id": "uuid:abc", "photo": "shot.jpg"}, form_ref="myform")
    atts = backend.list_attachments(sub)
    assert atts and atts[0]["name"] == "shot.jpg" and atts[0]["is_image"]
    assert atts[0]["question"] == "photo"
    # fetch_attachment → GET .../attachments/{name}
    stub = _HttpxStub(_Resp(content=b"CENTRALIMG"))
    monkeypatch.setattr(odkcentral.httpx, "Client", lambda *a, **k: stub)
    data, _ = backend.fetch_attachment(atts[0])
    assert data == b"CENTRALIMG"
    assert stub.url.endswith(
        "/v1/projects/7/forms/myform/submissions/uuid:abc/attachments/shot.jpg")
