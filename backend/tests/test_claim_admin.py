"""In-app Platform Admin bootstrap — the first user claims admin, then it closes."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.accounts.services import claim_admin_available, platform_admin_exists

pytestmark = pytest.mark.django_db


def _user(dj, email, active=True):
    return dj.objects.create_user(email, "pw", is_active=active)


def test_available_only_when_no_admin_and_active(django_user_model):
    u = _user(django_user_model, "first@x.org")
    assert claim_admin_available(u) is True


def test_unavailable_for_inactive_user(django_user_model):
    u = _user(django_user_model, "pending@x.org", active=False)
    assert claim_admin_available(u) is False


def test_unavailable_once_admin_exists(django_user_model):
    django_user_model.objects.create_superuser("admin@x.org", "pw")
    u = _user(django_user_model, "second@x.org")
    assert platform_admin_exists() is True
    assert claim_admin_available(u) is False


def test_claim_promotes_first_user(client, django_user_model):
    u = _user(django_user_model, "first@x.org")
    client.force_login(u)
    resp = client.post(reverse("claim_admin"))
    assert resp.status_code == 302
    u.refresh_from_db()
    assert u.is_superuser and u.is_staff
    assert u.is_platform_admin is True


def test_claim_closes_after_first(client, django_user_model):
    # An admin already exists; a later user cannot claim.
    django_user_model.objects.create_superuser("admin@x.org", "pw")
    u = _user(django_user_model, "late@x.org")
    client.force_login(u)
    resp = client.post(reverse("claim_admin"))
    assert resp.status_code == 302  # redirected, not promoted
    u.refresh_from_db()
    assert u.is_superuser is False


def test_claim_get_renders_when_available(client, django_user_model):
    u = _user(django_user_model, "first@x.org")
    client.force_login(u)
    resp = client.get(reverse("claim_admin"))
    assert resp.status_code == 200
    assert b"Claim Platform Admin" in resp.content


def test_claim_get_redirects_when_unavailable(client, django_user_model):
    django_user_model.objects.create_superuser("admin@x.org", "pw")
    u = _user(django_user_model, "x@x.org")
    client.force_login(u)
    resp = client.get(reverse("claim_admin"))
    assert resp.status_code == 302
