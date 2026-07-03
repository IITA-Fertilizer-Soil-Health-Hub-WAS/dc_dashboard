"""Collection-server webhook → instant re-sync (secret-guarded, debounced)."""
from __future__ import annotations

import pytest
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse

from apps.projects.models import Organization, Project

pytestmark = pytest.mark.django_db

SECRET = "s3cr3t"


@pytest.fixture
def uc():
    org = Organization.objects.create(code="o", name="O")
    return Project.objects.create(code="PROJ-A", name="A", organization=org, is_active=True)


@pytest.fixture
def captured(monkeypatch):
    """Capture webhook_ingest_task.delay calls instead of running a real sync."""
    calls = []
    monkeypatch.setattr(
        "apps.api.webhooks.webhook_ingest_task.delay",
        lambda code: calls.append(code),
    )
    cache.clear()
    return calls


def _url(code="PROJ-A"):
    return reverse("api:collection-webhook", args=[code])


@override_settings(COLLECTION_WEBHOOK_SECRET="")
def test_disabled_when_no_secret(client, uc, captured):
    resp = client.post(_url(), HTTP_X_WEBHOOK_TOKEN=SECRET)
    assert resp.status_code == 503
    assert captured == []


@override_settings(COLLECTION_WEBHOOK_SECRET=SECRET)
def test_bad_token_rejected(client, uc, captured):
    resp = client.post(_url(), HTTP_X_WEBHOOK_TOKEN="wrong")
    assert resp.status_code == 401
    assert captured == []


@override_settings(COLLECTION_WEBHOOK_SECRET=SECRET)
def test_unknown_project_404(client, captured):
    resp = client.post(_url("NOPE"), HTTP_X_WEBHOOK_TOKEN=SECRET)
    assert resp.status_code == 404
    assert captured == []


@override_settings(COLLECTION_WEBHOOK_SECRET=SECRET)
def test_valid_hit_queues_sync(client, uc, captured):
    resp = client.post(_url(), HTTP_X_WEBHOOK_TOKEN=SECRET)
    assert resp.status_code == 202
    assert resp.json()["status"] == "queued"
    assert captured == ["PROJ-A"]


@override_settings(COLLECTION_WEBHOOK_SECRET=SECRET)
def test_token_via_query_param(client, uc, captured):
    resp = client.post(_url() + f"?token={SECRET}")
    assert resp.status_code == 202
    assert captured == ["PROJ-A"]


@override_settings(COLLECTION_WEBHOOK_SECRET=SECRET, COLLECTION_WEBHOOK_DEBOUNCE_SECONDS=30)
def test_debounce_collapses_burst(client, uc, captured):
    first = client.post(_url(), HTTP_X_WEBHOOK_TOKEN=SECRET)
    second = client.post(_url(), HTTP_X_WEBHOOK_TOKEN=SECRET)
    assert first.json()["status"] == "queued"
    assert second.json()["status"] == "already_queued"
    assert captured == ["PROJ-A"]          # only one sync enqueued


@override_settings(COLLECTION_WEBHOOK_SECRET=SECRET)
def test_get_not_allowed(client, uc, captured):
    resp = client.get(_url(), HTTP_X_WEBHOOK_TOKEN=SECRET)
    assert resp.status_code == 405
