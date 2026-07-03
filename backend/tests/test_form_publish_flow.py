"""Stage A2/A3: publish service records a FormDefinition; admin upload screen."""
from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.ingestion.backends.base import PublishResult
from apps.ingestion.publishing import publish_xlsform
from apps.projects.models import FormDefinition, Project

pytestmark = pytest.mark.django_db


class _FakeBackend:
    label = "Fake"
    type = "FAKE"
    supports_publish = True

    def __init__(self, result):
        self._result = result

    def publish_form(self, xlsx, *, title=""):
        self._xlsx = xlsx
        return self._result


@pytest.fixture
def uc():
    return Project.objects.create(code="MAIZE", name="Maize Trial")


def _patch_backend(monkeypatch, result):
    backend = _FakeBackend(result)
    monkeypatch.setattr("apps.ingestion.publishing.get_backend_for", lambda u: backend)
    return backend


def test_server_ref_prefers_server_form_id():
    f1 = FormDefinition(server_form_id="maize_trial", ona_form_id=None)
    f2 = FormDefinition(server_form_id="", ona_form_id=750671)
    assert f1.server_ref == "maize_trial"
    assert f2.server_ref == "750671"


def test_publish_service_records_form(monkeypatch, uc):
    _patch_backend(monkeypatch, PublishResult(
        ok=True, server_form_id="maize_v1", version="2024a", title="Maize Trial"))
    form, result = publish_xlsform(uc, b"<xlsx>", filename="maize.xlsx", role="VALIDATION")
    assert result.ok
    assert form.project == uc
    assert form.server_form_id == "maize_v1"
    assert form.publish_status == FormDefinition.PublishStatus.PUBLISHED
    assert form.published_at is not None
    assert form.title == "Maize Trial"
    assert form.xlsform.name.endswith(".xlsx")


def test_publish_service_numeric_id_sets_ona_form_id(monkeypatch, uc):
    _patch_backend(monkeypatch, PublishResult(ok=True, server_form_id="998877"))
    form, _ = publish_xlsform(uc, b"<xlsx>", filename="f.xlsx", role="VALIDATION")
    assert form.server_form_id == "998877"
    assert form.ona_form_id == 998877  # numeric server id mirrored for ONA


def test_publish_service_surfaces_failure(monkeypatch, uc):
    _patch_backend(monkeypatch, PublishResult(ok=False, message="Bad XLSForm: unknown type"))
    form, result = publish_xlsform(uc, b"<bad>", filename="f.xlsx", role="VALIDATION")
    assert form is None
    assert not result.ok
    assert FormDefinition.objects.count() == 0


def test_publish_unsupported_backend(monkeypatch, uc):
    class NoPublish:
        label = "CSV"
        type = "CSV"
        supports_publish = False
    monkeypatch.setattr("apps.ingestion.publishing.get_backend_for", lambda u: NoPublish())
    form, result = publish_xlsform(uc, b"x", filename="f.xlsx", role="VALIDATION")
    assert form is None
    assert "does not support publishing" in result.message


def test_publish_view_uploads_and_creates_form(client, django_user_model, monkeypatch, uc):
    _patch_backend(monkeypatch, PublishResult(
        ok=True, server_form_id="maize_v1", title="Maize Trial"))
    admin = django_user_model.objects.create_superuser("a@x.org", "pw")
    client.force_login(admin)
    upload = SimpleUploadedFile(
        "maize.xlsx", b"<xlsx-bytes>",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp = client.post(reverse("console:publish_form"),
                       {"project": str(uc.pk), "role": "VALIDATION", "xlsform": upload})
    assert resp.status_code == 302  # success → redirect to forms list
    assert FormDefinition.objects.filter(project=uc, server_form_id="maize_v1").exists()


def test_publish_view_shows_error(client, django_user_model, monkeypatch, uc):
    _patch_backend(monkeypatch, PublishResult(ok=False, message="Conversion failed"))
    admin = django_user_model.objects.create_superuser("a2@x.org", "pw")
    client.force_login(admin)
    upload = SimpleUploadedFile("bad.xlsx", b"<bad>")
    resp = client.post(reverse("console:publish_form"),
                       {"project": str(uc.pk), "role": "VALIDATION", "xlsform": upload})
    assert resp.status_code == 200
    assert b"Conversion failed" in resp.content
    assert FormDefinition.objects.count() == 0


def test_publish_view_staff_only(client, django_user_model, uc):
    user = django_user_model.objects.create_user("u@x.org", "pw", is_active=True)
    client.force_login(user)
    assert client.get(reverse("console:publish_form")).status_code == 403
