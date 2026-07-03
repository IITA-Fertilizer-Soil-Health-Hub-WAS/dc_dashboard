"""Every user must fill their profile before approval.

A not-yet-approved account can log in (is_active) but is trapped by the gate
middleware on the profile → pending flow until an admin reviews the profile.
"""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.accounts.models import UserProfile

pytestmark = pytest.mark.django_db


def _pending(django_user_model, email="pend@x.org"):
    # Active (can hold a session) but not approved — the Auth0-provisioned state.
    return django_user_model.objects.create_user(email, "pw", is_active=True, is_approved=False)


def _valid_profile_post():
    return {
        "first_name": "Ada", "second_name": "", "family_name": "Kofi",
        "gender": "female", "age": "31", "education_level": "secondary",
        "experience_years": "2",
        "phone": "+233200000000", "phone_alt": "", "country": "Ghana",
        "consent_personal_info": "on", "consent_followup": "", "consent_photos": "",
    }


def test_pending_user_without_profile_is_sent_to_profile(client, django_user_model):
    user = _pending(django_user_model)
    client.force_login(user)
    resp = client.get(reverse("dashboards:index"))
    assert resp.status_code == 302
    assert resp.url == reverse("profile")


def test_pending_user_can_open_profile(client, django_user_model):
    user = _pending(django_user_model)
    client.force_login(user)
    assert client.get(reverse("profile")).status_code == 200


def test_submitting_profile_sends_pending_user_to_waiting_page(client, django_user_model):
    user = _pending(django_user_model)
    client.force_login(user)
    resp = client.post(reverse("profile"), _valid_profile_post())
    assert resp.status_code == 302
    assert resp.url == reverse("pending")
    assert UserProfile.objects.get(user=user).is_complete
    user.refresh_from_db()
    assert user.is_approved is False  # still awaiting an admin


def test_pending_user_with_profile_is_sent_to_pending_page(client, django_user_model):
    user = _pending(django_user_model)
    UserProfile.objects.create(user=user, completed_at="2026-01-01T00:00:00Z")
    client.force_login(user)
    resp = client.get(reverse("dashboards:index"))
    assert resp.status_code == 302
    assert resp.url == reverse("pending")


def test_pending_page_requires_submitted_profile(client, django_user_model):
    user = _pending(django_user_model)  # no profile yet
    client.force_login(user)
    resp = client.get(reverse("pending"))
    assert resp.status_code == 302
    assert resp.url == reverse("profile")


def test_approved_user_passes_through(client, django_user_model):
    user = django_user_model.objects.create_user(
        "ok@x.org", "pw", is_active=True, is_approved=True
    )
    client.force_login(user)
    # Not redirected into the gate (may 200, or redirect elsewhere — never to profile/pending).
    resp = client.get(reverse("dashboards:index"))
    assert resp.status_code == 200 or resp.url not in (reverse("profile"), reverse("pending"))


def test_superuser_is_exempt_from_gate(client, django_user_model):
    su = django_user_model.objects.create_superuser("root@x.org", "pw")
    client.force_login(su)
    resp = client.get(reverse("dashboards:index"))
    assert resp.status_code == 200
