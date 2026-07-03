"""Generic data-collection backend abstraction + per-use-case DataSource."""
from __future__ import annotations

import pytest

from apps.ingestion.backends.base import CollectionBackend, RemoteForm, RemoteProject, WriteResult
from apps.ingestion.backends.ona import OnaBackend
from apps.ingestion.backends.registry import build_backend, get_backend_for
from apps.ingestion.sync import sync_project
from apps.usecases.models import DataSource, FormDefinition, Project

pytestmark = pytest.mark.django_db


def test_default_and_explicit_backend():
    assert isinstance(build_backend(), OnaBackend)
    assert isinstance(build_backend("ONA"), OnaBackend)
    # Unknown type falls back to ONA rather than crashing.
    assert isinstance(build_backend("MARS"), OnaBackend)


def test_get_backend_for_uses_datasource():
    uc = Project.objects.create(code="X", name="X")
    # No DataSource -> ONA from global settings.
    assert isinstance(get_backend_for(uc), OnaBackend)
    DataSource.objects.create(project=uc, backend="ONA", base_url="https://k.example", token="tok")
    backend = get_backend_for(uc)
    assert backend.base_url == "https://k.example"
    assert backend.token == "tok"


def test_writeback_unsupported_by_default():
    res = CollectionBackend(base_url="x").push_edit(submission=None, changes={})
    assert isinstance(res, WriteResult) and res.ok is False


class FakeBackend(CollectionBackend):
    """A non-ONA backend proving the engine is provider-agnostic."""

    type = "FAKE"
    label = "Fake server"

    def __init__(self, data):
        super().__init__()
        self._data = data

    def get_submissions(self, form_id):
        return self._data.get(int(form_id), [])


def test_sync_runs_through_any_backend():
    uc = Project.objects.create(code="FAKEUC", name="Fake")
    form = FormDefinition.objects.create(project=uc, ona_form_id=42,
                                         role=FormDefinition.Role.VALIDATION)
    from apps.usecases.models import FieldMapping
    FieldMapping.objects.create(form=form, target_field="ENID", source_paths=["enid"])
    FieldMapping.objects.create(form=form, target_field="event_key", source_paths=["event"])

    backend = FakeBackend({42: [{"_uuid": "u1", "enid": "EN1", "event": "Event1"}]})
    stats = sync_project(uc, backend=backend)
    assert stats.created == 1
    assert uc.submissions.filter(ona_uuid="u1").exists()


def test_ona_backend_discovers_projects(monkeypatch):
    from apps.ingestion import ona_client

    class FakeResp:
        status_code = 200

        def __init__(self, payload):
            self._p = payload

        def json(self):
            return self._p

    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False

        def get(self, url, **k):
            return FakeResp([
                {"projectid": 7, "name": "SNS Rwanda",
                 "forms": [{"formid": 100, "title": "Validation"}]},
            ])

    monkeypatch.setattr(ona_client.httpx, "Client", FakeClient)
    projects = OnaBackend(token="t").discover_projects()
    assert projects == [RemoteProject(id="7", name="SNS Rwanda",
                                      forms=[RemoteForm(id="100", title="Validation")])]


def test_onboarding_config_includes_data_source():
    from apps.console.onboarding import build_config

    cfg = build_config({"code": "DS1", "name": "DS One", "backend": "ONA",
                        "base_url": "https://api.ona.io", "token": "abc",
                        "form_count": "0"})
    assert cfg["data_source"] == {"backend": "ONA", "base_url": "https://api.ona.io", "token": "abc"}


def test_loader_creates_data_source():
    from apps.config_admin.loader import import_config

    uc = import_config({
        "project": {"code": "DSUC", "name": "DS UC"},
        "data_source": {"backend": "ONA", "base_url": "https://api.ona.io", "token": "zzz"},
        "forms": [{"ona_form_id": 1, "role": "VALIDATION",
                   "mappings": [{"target": "event_key", "source": ["e"]}]}],
    })
    assert uc.data_source.backend == "ONA"
    assert uc.data_source.token == "zzz"
