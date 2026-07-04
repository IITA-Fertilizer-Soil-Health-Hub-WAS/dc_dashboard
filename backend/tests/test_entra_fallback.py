"""Auth0 and Entra ID are both offered on the login page as provider choices.
Auth0 stays the primary (green) button; the Entra button only appears when Entra
is configured, so it's an opt-in choice, never a swap."""
from __future__ import annotations

import pytest
from django.test import override_settings
from django.urls import reverse

pytestmark = pytest.mark.django_db


@override_settings(AUTH0_CONFIGURED=True)
def test_login_shows_auth0_provider(client):
    resp = client.get(reverse("login"))
    assert resp.status_code == 200
    # Auth0 is the primary path (one button routes both sign-in and sign-up).
    assert b"Continue with Auth0" in resp.content


@override_settings(AUTH0_CONFIGURED=True, ENTRA_CONFIGURED=False)
def test_entra_button_hidden_when_unconfigured(client):
    resp = client.get(reverse("login"))
    assert resp.status_code == 200
    assert b"Continue with Microsoft" not in resp.content


@override_settings(
    AUTH0_CONFIGURED=True,
    ENTRA_CONFIGURED=True,
    ENTRA_LOGIN_URL="/accounts/oidc/entra/login/",
)
def test_both_providers_offered_when_entra_configured(client):
    resp = client.get(reverse("login"))
    assert resp.status_code == 200
    # Both providers are offered as choices…
    assert b"Continue with Auth0" in resp.content
    assert b"Continue with Microsoft" in resp.content
    assert b"/accounts/oidc/entra/login/" in resp.content


@override_settings(AUTH0_CONFIGURED=False, ENTRA_CONFIGURED=True,
                   ENTRA_LOGIN_URL="/accounts/oidc/entra/login/")
def test_entra_alone_still_offers_signin(client):
    # Even if Auth0 is down/unconfigured, Entra alone keeps sign-in working.
    resp = client.get(reverse("login"))
    assert resp.status_code == 200
    assert b"Continue with Microsoft" in resp.content
    assert b"Continue with Auth0" not in resp.content
