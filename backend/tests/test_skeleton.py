"""Phase 1 smoke tests: the project boots and the health check responds."""
from __future__ import annotations

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_healthcheck_ok(client):
    resp = client.get(reverse("healthcheck"))
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.django_db
def test_index_requires_login(client):
    # The landing page is the RBAC-scoped use-case list; anonymous users are
    # redirected to the /login/ entry point (the only sign-in path).
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login/" in resp["Location"]


@pytest.mark.django_db
def test_local_signup_redirects_to_login(client):
    # Local email/password signup is disabled — it redirects to /login/.
    resp = client.get("/accounts/signup/")
    assert resp.status_code == 302
    assert "/login/" in resp["Location"]


@pytest.mark.django_db
def test_login_page_degrades_without_auth0(client, settings):
    # When Auth0 isn't configured, the login page renders a clear message rather
    # than 500-ing on the OIDC discovery fetch.
    settings.AUTH0_CONFIGURED = False
    resp = client.get("/login/")
    assert resp.status_code == 200
    assert b"Auth0 is not configured" in resp.content


@pytest.mark.django_db
def test_login_page_shows_button_when_configured(client, settings):
    settings.AUTH0_CONFIGURED = True
    resp = client.get("/login/")
    assert resp.status_code == 200
    assert b"Sign in" in resp.content
    assert b"Create an account" in resp.content
