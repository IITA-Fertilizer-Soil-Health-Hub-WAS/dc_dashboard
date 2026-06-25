"""Kobo + ODK Central backends: registration, discovery parsing, shared write-back."""
from __future__ import annotations

from apps.ingestion.backends.base import RemoteForm, RemoteProject
from apps.ingestion.backends.kobo import KoboBackend
from apps.ingestion.backends.odk import OdkBackend
from apps.ingestion.backends.odkcentral import OdkCentralBackend
from apps.ingestion.backends.registry import BACKEND_CHOICES, build_backend


def test_backends_registered_for_onboarding():
    values = {v for v, _ in BACKEND_CHOICES}
    assert {"ONA", "KOBO", "ODK_CENTRAL"} <= values


def test_build_each_backend_type():
    assert isinstance(build_backend("KOBO"), KoboBackend)
    assert isinstance(build_backend("ODK_CENTRAL"), OdkCentralBackend)


def test_all_share_generic_odk_writeback():
    # The write-back engine is inherited, not reimplemented per server.
    for cls in (KoboBackend, OdkCentralBackend):
        assert issubclass(cls, OdkBackend)
        assert cls.supports_writeback is True


def _mock_httpx(monkeypatch, module, payloads):
    """Patch a backend module's httpx.Client to return queued JSON payloads."""
    import apps.ingestion.backends as pkg
    target = getattr(pkg, module)

    class FakeResp:
        status_code = 200

        def __init__(self, payload):
            self._p = payload

        def json(self):
            return self._p

    seq = iter(payloads)

    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False

        def get(self, *a, **k):
            return FakeResp(next(seq))

    monkeypatch.setattr(target.httpx, "Client", FakeClient)


def test_kobo_discovery_parses_assets(monkeypatch):
    _mock_httpx(monkeypatch, "kobo", [
        {"results": [
            {"uid": "aXYZ", "name": "Maize Trial", "asset_type": "survey"},
            {"uid": "aLIB", "name": "Library item", "asset_type": "template"},  # ignored
        ]},
    ])
    projects = KoboBackend(token="t").discover_projects()
    assert projects == [RemoteProject(id="aXYZ", name="Maize Trial",
                                      forms=[RemoteForm(id="aXYZ", title="Maize Trial")])]


def test_odk_central_discovery_parses_projects(monkeypatch):
    # 1st GET: projects list; 2nd GET: that project's forms.
    _mock_httpx(monkeypatch, "odkcentral", [
        [{"id": 3, "name": "Sierra Leone"}],
        [{"xmlFormId": "trial_reg", "name": "Trial Registration"}],
    ])
    projects = OdkCentralBackend(base_url="https://c.example", token="t").discover_projects()
    assert projects == [RemoteProject(id="3", name="Sierra Leone",
                                      forms=[RemoteForm(id="trial_reg", title="Trial Registration")])]
