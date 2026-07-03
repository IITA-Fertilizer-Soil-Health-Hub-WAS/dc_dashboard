"""Idempotent Platform Admin bootstrap command."""
from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db


def _run(**kw):
    out = StringIO()
    call_command("bootstrap_admin", stdout=out, stderr=out, **kw)
    return out.getvalue()


def test_creates_admin_when_none(django_user_model):
    _run(email="boss@x.org", password="s3cret-pw")
    u = django_user_model.objects.get(email="boss@x.org")
    assert u.is_superuser and u.is_staff and u.is_active and u.email_verified
    assert u.check_password("s3cret-pw")


def test_idempotent_when_admin_exists(django_user_model):
    django_user_model.objects.create_superuser("first@x.org", "pw")
    out = _run(email="second@x.org", password="pw2")
    assert "already exists" in out
    assert not django_user_model.objects.filter(email="second@x.org").exists()


def test_promotes_existing_account(django_user_model):
    # e.g. someone who already signed in via Auth0 (inactive, non-staff)
    u = django_user_model.objects.create_user("me@x.org", "old", is_active=False)
    _run(email="ME@x.org", password="new-pw")   # case-insensitive match
    u.refresh_from_db()
    assert u.is_superuser and u.is_active and u.check_password("new-pw")


def test_skips_quietly_without_credentials(django_user_model):
    out = _run()  # no admin, no email/password → must not fail startup
    assert "skipping" in out.lower()
    assert not django_user_model.objects.filter(is_superuser=True).exists()
