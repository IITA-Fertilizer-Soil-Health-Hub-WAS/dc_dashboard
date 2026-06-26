"""The dev-only style preview is reachable without auth only when DEBUG is on."""
from __future__ import annotations

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_hidden_in_production(client, settings):
    settings.DEBUG = False
    assert client.get(reverse("dashboards:style_preview")).status_code == 404


def test_visible_without_auth_in_debug(client, settings):
    settings.DEBUG = True
    resp = client.get(reverse("dashboards:style_preview"))  # no login
    assert resp.status_code == 200
    assert b"Component preview" in resp.content
    assert b"class=\"chip ext\"" in resp.content
