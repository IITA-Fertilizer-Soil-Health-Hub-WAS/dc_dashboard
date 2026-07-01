"""SDMT-inspired #2: photos/media in the review screen."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.ingestion.attachments import parse_attachments
from apps.rbac.models import Role, UseCaseMembership
from apps.submissions.models import Submission
from apps.usecases.models import FormDefinition, Organization, UseCase

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
    uc = UseCase.objects.create(code="PROJ-A", name="A", organization=org)
    form = FormDefinition.objects.create(use_case=uc, ona_form_id=1, role=FormDefinition.Role.VALIDATION)
    sub = Submission.objects.create(use_case=uc, form=form, ona_uuid="m1",
                                    content_hash="h", raw_payload=PAYLOAD)
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True, organization=org)
    UseCaseMembership.objects.create(user=coord, use_case=uc, role=Role.TRIAL_COORDINATOR)
    return {"uc": uc, "sub": sub, "coord": coord}


def test_review_screen_shows_media_gallery(client, world):
    client.force_login(world["coord"])
    url = reverse("dashboards:submission_review", args=["PROJ-A", world["sub"].id])
    page = client.get(url).content
    media_url = reverse("dashboards:submission_media", args=["PROJ-A", world["sub"].id, 501])
    assert media_url.encode() in page  # image proxied through the app
    assert b"voice_1.mp3" in page


def test_media_proxy_streams_and_scopes(client, world, monkeypatch):
    class StubBackend:
        def fetch_attachment(self, attachment_id):
            return b"JPEGBYTES", "image/jpeg"

    monkeypatch.setattr("apps.ingestion.backends.registry.get_backend_for",
                        lambda uc: StubBackend())
    client.force_login(world["coord"])
    ok = reverse("dashboards:submission_media", args=["PROJ-A", world["sub"].id, 501])
    resp = client.get(ok)
    assert resp.status_code == 200 and resp["Content-Type"] == "image/jpeg"
    assert resp.content == b"JPEGBYTES"
    # An id not on this submission's record is rejected.
    bad = reverse("dashboards:submission_media", args=["PROJ-A", world["sub"].id, 999])
    assert client.get(bad).status_code == 404
