"""Stage A1: CollectionBackend.publish_form pushes an XLSForm to the server."""
from __future__ import annotations

from apps.ingestion.backends import odkcentral, ona
from apps.ingestion.backends.base import CollectionBackend
from apps.ingestion.backends.kobo import KoboBackend
from apps.ingestion.backends.odkcentral import OdkCentralBackend
from apps.ingestion.backends.ona import OnaBackend


def _mock_post(monkeypatch, module, status, payload):
    """Patch a backend module's httpx.Client so .post returns a canned response."""

    class FakeResp:
        status_code = status
        text = str(payload)

        def json(self):
            return payload

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            self.captured = k
            return FakeResp()

    monkeypatch.setattr(module.httpx, "Client", FakeClient)


def test_odk_central_publish_success(monkeypatch):
    _mock_post(monkeypatch, odkcentral, 200, {
        "xmlFormId": "maize_trial", "version": "2024a", "name": "Maize Trial",
    })
    b = OdkCentralBackend(base_url="https://central.example", token="t",
                          config={"project_id": 5})
    res = b.publish_form(b"<xlsx-bytes>", title="Maize Trial")
    assert res.ok
    assert res.server_form_id == "maize_trial"
    assert res.version == "2024a"
    assert res.title == "Maize Trial"
    assert "projects/5/forms/maize_trial" in res.url


def test_odk_central_publish_conversion_error(monkeypatch):
    _mock_post(monkeypatch, odkcentral, 400, {
        "message": "The XLSForm could not be converted",
        "details": {"warnings": "unknown question type 'banana'"},
    })
    b = OdkCentralBackend(base_url="https://central.example", token="t",
                          config={"project_id": 5})
    res = b.publish_form(b"<bad-xlsx>")
    assert not res.ok
    assert "could not be converted" in res.message
    assert res.server_form_id is None


def test_ona_publish_success(monkeypatch):
    _mock_post(monkeypatch, ona, 201, {
        "formid": 998877, "id_string": "maize_trial", "title": "Maize Trial",
    })
    b = OnaBackend(base_url="https://api.ona.io", token="t")
    res = b.publish_form(b"<xlsx-bytes>")
    assert res.ok
    assert res.server_form_id == "998877"
    assert res.title == "Maize Trial"


def test_ona_publish_error(monkeypatch):
    _mock_post(monkeypatch, ona, 400, {"text": "Header name conflict"})
    b = OnaBackend(base_url="https://api.ona.io", token="t")
    res = b.publish_form(b"<bad-xlsx>")
    assert not res.ok
    assert "Header name conflict" in res.message


def test_publish_unsupported_by_default():
    res = CollectionBackend().publish_form(b"x")
    assert not res.ok
    assert "does not support form publishing" in res.message
    # Kobo has no publish yet -> inherits the unsupported default.
    assert KoboBackend(token="t").supports_publish is False


def test_publish_capability_flags():
    assert OdkCentralBackend().supports_publish is True
    assert OnaBackend().supports_publish is True
