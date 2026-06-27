"""Entra ID is an optional FALLBACK provider — Auth0 stays primary, and the
Entra button only appears when Entra is configured."""
from __future__ import annotations

import pytest
from django.test import override_settings
from django.urls import reverse

pytestmark = pytest.mark.django_db


@override_settings(AUTH0_CONFIGURED=True)
def test_login_shows_auth0_always(client):
    resp = client.get(reverse("login"))
    assert resp.status_code == 200
    # Auth0 is the primary path; its button text is present.
    assert b"Continue with Auth0" in resp.content


@override_settings(AUTH0_CONFIGURED=True, ENTRA_CONFIGURED=False)
def test_entra_button_hidden_when_unconfigured(client):
    resp = client.get(reverse("login"))
    assert resp.status_code == 200
    assert b"continue with Microsoft" not in resp.content


@override_settings(
    AUTH0_CONFIGURED=True,
    ENTRA_CONFIGURED=True,
    ENTRA_LOGIN_URL="/accounts/oidc/entra/login/",
)
def test_entra_button_shown_as_fallback_when_configured(client):
    resp = client.get(reverse("login"))
    assert resp.status_code == 200
    # Auth0 still primary…
    assert b"Continue with Auth0" in resp.content
    # …and Entra offered as a CGIAR-staff fallback.
    assert b"continue with Microsoft" in resp.content
    assert b"/accounts/oidc/entra/login/" in resp.content
