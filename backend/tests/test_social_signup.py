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
    from apps.projects.models import Organization

    org = Organization.objects.create(code="iita", name="IITA")
    form = _bound_form(organization=str(org.id))
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


def test_signup_can_pick_institution(django_user_model):
    # When institutions exist, the account is linked to the chosen one.
    from apps.projects.models import Organization

    org = Organization.objects.create(code="iita", name="IITA")
    form = _bound_form(organization=str(org.id))
    assert form.is_valid(), form.errors
    user = django_user_model.objects.create_user("newbie@x.org", "pw")
    form.custom_signup(_make_request(), user)
    user.refresh_from_db()
    assert user.organization_id == org.id


def test_signup_requires_institution_when_onboarded():
    # Institution is mandatory; the dropdown is the Platform-Admin-onboarded list.
    from apps.projects.models import Organization

    Organization.objects.create(code="iita", name="IITA")
    form = _bound_form()                 # institution onboarded but none chosen
    assert not form.is_valid()
    assert "organization" in form.errors


def test_signup_always_requires_institution():
    # Enforced even with none onboarded yet — registration never slips through
    # without one (the first admin bootstraps via Create-platform-admin instead).
    form = _bound_form()                 # no orgs exist, none chosen
    assert not form.is_valid()
    assert "organization" in form.errors


def test_signup_requires_name_and_country():
    form = _bound_form(first_name="", family_name="", country="")
    assert not form.is_valid()
    assert "first_name" in form.errors
    assert "family_name" in form.errors
    assert "country" in form.errors


def test_new_user_is_routed_to_create_account_not_signed_in():
    """A first-time Auth0 user must NOT be silently signed in. With auto-signup
    off, allauth's process_signup sends a brand-new social login to the
    create-account form (redirect_to_signup) instead of creating + logging in
    the account. This guards the decision point that enforces that."""
    from django.conf import settings
    from django.test import RequestFactory

    from apps.accounts.adapters import SocialAccountAdapter

    assert settings.SOCIALACCOUNT_AUTO_SIGNUP is False
    new_login = _sociallogin("first.timer@cgiar.org")
    allowed = SocialAccountAdapter().is_auto_signup_allowed(
        RequestFactory().get("/"), new_login
    )
    assert allowed is False  # → allauth redirects to the create-account form
