"""First-run 'Create platform admin' from the login page (pre-auth)."""
from __future__ import annotations

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_login_page_offers_create_admin_when_none(client):
    body = client.get(reverse("login")).content.decode()
    assert "Create platform admin" in body


def test_login_page_hides_link_once_admin_exists(client, django_user_model):
    django_user_model.objects.create_superuser("a@x.org", "pw")
    body = client.get(reverse("login")).content.decode()
    assert "Create platform admin" not in body


def test_create_admin_creates_and_signs_in(client, django_user_model):
    resp = client.post(reverse("create_admin"), {
        "email": "Boss@x.org", "password": "s3cret-pw", "confirm": "s3cret-pw",
    })
    assert resp.status_code == 302 and resp.url == reverse("dashboards:index")
    u = django_user_model.objects.get(email="boss@x.org")
    assert u.is_superuser and u.is_staff and u.is_active
    assert "_auth_user_id" in client.session  # logged in


def test_create_admin_validates_password(client, django_user_model):
    client.post(reverse("create_admin"),
                {"email": "b@x.org", "password": "short", "confirm": "short"})
    assert not django_user_model.objects.filter(email="b@x.org").exists()
    body = client.post(reverse("create_admin"),
                       {"email": "b@x.org", "password": "longenough", "confirm": "nomatch"}).content.decode()
    assert "do not match" in body.lower()
    assert not django_user_model.objects.filter(email="b@x.org").exists()


def test_create_admin_closed_once_admin_exists(client, django_user_model):
    django_user_model.objects.create_superuser("a@x.org", "pw")
    resp = client.post(reverse("create_admin"),
                       {"email": "b@x.org", "password": "s3cret-pw", "confirm": "s3cret-pw"})
    assert resp.status_code == 302 and resp.url == reverse("login")
    assert not django_user_model.objects.filter(email="b@x.org").exists()
