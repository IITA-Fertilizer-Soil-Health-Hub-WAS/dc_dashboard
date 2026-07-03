"""The one-step signup form: the account (User + completed UserProfile) is only
created after the person submits everything, and it lands inactive/pending."""
from __future__ import annotations

import pytest

from apps.accounts.forms import SocialSignupForm
from apps.accounts.models import User, UserProfile

pytestmark = pytest.mark.django_db


def _sociallogin(email="newbie@x.org"):
    """A minimal SocialLogin allauth would hand the signup form for a new user."""
    from allauth.socialaccount.models import SocialLogin

    user = User(email=email)
    return SocialLogin(user=user, email_addresses=[])


def _bound_form(**over):
    form = SocialSignupForm(_post(**over), sociallogin=_sociallogin())
    return form


def _post(**over):
    data = {
        "email": "newbie@x.org",
        "first_name": "Ama", "second_name": "", "family_name": "Mensah",
        "phone": "+233200000000", "country": "Ghana",
        "gender": "female", "age": "29", "education_level": "secondary",
        "experience_years": "3", "phone_alt": "",
        "consent_personal_info": "on",
    }
    data.update(over)
    return data


def _make_request():
    from django.contrib.messages.storage.fallback import FallbackStorage
    from django.contrib.sessions.backends.db import SessionStore
    from django.test import RequestFactory

    req = RequestFactory().post("/accounts/social/signup/")
    req.session = SessionStore()
    req._messages = FallbackStorage(req)
    return req


def test_signup_captures_completed_profile(django_user_model):
    # allauth validates (no account exists yet), creates the inactive account,
    # then calls custom_signup — our code — to persist name/phone + the profile.
    form = _bound_form()
    assert form.is_valid(), form.errors
    user = django_user_model.objects.create_user("newbie@x.org", "pw")  # inactive by default
    form.custom_signup(_make_request(), user)

    user.refresh_from_db()
    assert user.full_name == "Ama Mensah"          # composed from the name boxes
    assert user.phone == "+233200000000"
    assert user.is_active is False                  # pending admin approval

    prof = UserProfile.objects.get(user=user)
    assert prof.is_complete                          # captured in the same step
    assert prof.country == "Ghana"
    assert prof.experience_years == 3
    assert prof.consent_personal_info is True


def test_signup_requires_name_and_country():
    form = _bound_form(first_name="", family_name="", country="")
    assert not form.is_valid()
    assert "first_name" in form.errors
    assert "family_name" in form.errors
    assert "country" in form.errors
