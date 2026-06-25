"""Auth0 + admin-approval: new users land inactive until approved; the approval
is auditable. Approve/Deactivate now live as console actions."""
from __future__ import annotations

import pytest
from django.test import RequestFactory

from apps.accounts import adapters
from apps.console.actions import user_approve, user_deactivate

pytestmark = pytest.mark.django_db


def _request(user):
    req = RequestFactory().post("/manage/users/")
    req.user = user
    return req


def test_approval_is_required_by_default():
    # Both controls are on: Auth0 is the only login AND admin approval is required.
    assert adapters.REQUIRE_ADMIN_APPROVAL_FOR_AUTH0 is True


def test_new_user_is_inactive_until_approved(django_user_model):
    # create_user mirrors how a fresh (Auth0-provisioned) account starts.
    user = django_user_model.objects.create_user("new@x.org", "pw")
    assert user.is_active is False


def test_approve_action_activates_and_audits(django_user_model):
    admin_user = django_user_model.objects.create_superuser("admin@x.org", "pw")
    pending = django_user_model.objects.create_user("pending@x.org", "pw")
    assert pending.is_active is False

    user_approve(_request(admin_user), pending)

    pending.refresh_from_db()
    assert pending.is_active is True
    assert pending.approved_by == admin_user
    assert pending.approved_at is not None


def test_deactivate_action_revokes(django_user_model):
    admin_user = django_user_model.objects.create_superuser("admin@x.org", "pw")
    active = django_user_model.objects.create_user("a@x.org", "pw", is_active=True)

    user_deactivate(_request(admin_user), active)
    active.refresh_from_db()
    assert active.is_active is False
