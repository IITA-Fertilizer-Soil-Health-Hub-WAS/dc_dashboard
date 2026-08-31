"""An incomplete identity profile hard-gates the whole platform."""
import pytest
from django.urls import reverse

from apps.accounts.models import UserProfile

pytestmark = pytest.mark.django_db


def test_incomplete_profile_is_redirected_to_the_profile_form(client, django_user_model, settings):
    settings.REQUIRE_COMPLETE_PROFILE = True
    u = django_user_model.objects.create_user("u@x.org", "pw", is_active=True)
    client.force_login(u)
    resp = client.get("/")                       # any app page…
    assert resp.status_code == 302 and resp.url == reverse("profile")  # …bounces to /profile/


def test_profile_form_and_health_stay_reachable_when_incomplete(client, django_user_model, settings):
    settings.REQUIRE_COMPLETE_PROFILE = True
    u = django_user_model.objects.create_user("u2@x.org", "pw", is_active=True)
    client.force_login(u)
    assert client.get(reverse("profile")).status_code == 200   # the escape hatch
    assert client.get("/healthz/").status_code == 200          # exempt


def test_complete_profile_is_not_gated(client, django_user_model, settings):
    settings.REQUIRE_COMPLETE_PROFILE = True
    u = django_user_model.objects.create_user("u3@x.org", "pw", is_active=True)
    UserProfile.objects.get_or_create(user=u)[0].mark_complete()
    client.force_login(u)
    resp = client.get("/")
    assert not (resp.status_code == 302 and resp.url == reverse("profile"))
