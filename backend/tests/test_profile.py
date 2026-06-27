"""One-time 'register once' user profile (replaces the field ODK enumerator form)."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.accounts.models import UserProfile

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user("e@x.org", "pw", is_active=True)


def _valid_post():
    return {
        "first_name": "Ama", "second_name": "", "family_name": "Mensah",
        "gender": "female", "age": "29", "education_level": "secondary",
        "experience_years": "4",
        "phone": "+233200000000", "phone_alt": "", "country": "Ghana",
        "consent_personal_info": "on", "consent_followup": "on", "consent_photos": "",
    }


def test_profile_page_renders(client, user):
    client.force_login(user)
    resp = client.get(reverse("profile"))
    assert resp.status_code == 200
    assert b"My profile" in resp.content


def test_submitting_profile_marks_complete_and_syncs(client, user):
    client.force_login(user)
    resp = client.post(reverse("profile"), _valid_post())
    assert resp.status_code == 302
    prof = UserProfile.objects.get(user=user)
    assert prof.is_complete
    assert prof.first_name == "Ama" and prof.family_name == "Mensah"
    assert prof.experience_years == 4
    assert prof.consent_personal_info is True and prof.consent_photos is False
    user.refresh_from_db()
    assert user.full_name == "Ama Mensah"          # display name synced
    assert user.phone == "+233200000000"            # primary phone synced to User


def test_required_fields_validated(client, user):
    client.force_login(user)
    bad = _valid_post() | {"first_name": "", "country": ""}
    resp = client.post(reverse("profile"), bad)
    assert resp.status_code == 200                   # re-renders with errors
    assert not UserProfile.objects.filter(user=user, completed_at__isnull=False).exists()


def test_incomplete_profile_prompts_in_shell(client, user):
    client.force_login(user)
    # Before completing, the prompt banner is present on other pages.
    other = client.get(reverse("dashboards:projects")).content
    assert b"Complete your profile" in other
    client.post(reverse("profile"), _valid_post())
    after = client.get(reverse("dashboards:projects")).content
    assert b"Complete your profile" not in after    # gone once complete
