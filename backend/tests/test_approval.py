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
    from django.utils import timezone

    from apps.accounts.models import UserProfile
    from apps.projects.models import Organization

    admin_user = django_user_model.objects.create_superuser("admin@x.org", "pw")
    org = Organization.objects.create(code="inst", name="Institution")
    pending = django_user_model.objects.create_user(
        "pending@x.org", "pw", organization=org
    )
    assert pending.is_active is False
    # Approval reviews the profile submitted at registration.
    UserProfile.objects.create(user=pending, completed_at=timezone.now())

    user_approve(_request(admin_user), pending)

    pending.refresh_from_db()
    assert pending.is_active is True
    assert pending.approved_by == admin_user
    assert pending.approved_at is not None


def test_approve_refused_without_institution(django_user_model):
    from django.utils import timezone

    from apps.accounts.models import UserProfile

    admin_user = django_user_model.objects.create_superuser("admin3@x.org", "pw")
    pending = django_user_model.objects.create_user("noorg@x.org", "pw")  # no org
    UserProfile.objects.create(user=pending, completed_at=timezone.now())

    msg = user_approve(_request(admin_user), pending)

    pending.refresh_from_db()
    assert pending.is_active is False              # not approved without an institution
    assert "institution" in msg.lower()


def test_approve_refused_without_submitted_profile(django_user_model):
    admin_user = django_user_model.objects.create_superuser("admin2@x.org", "pw")
    pending = django_user_model.objects.create_user("noprofile@x.org", "pw")

    msg = user_approve(_request(admin_user), pending)

    pending.refresh_from_db()
    assert pending.is_active is False
    assert "profile" in msg.lower()


def test_deactivate_action_revokes(django_user_model):
    admin_user = django_user_model.objects.create_superuser("admin@x.org", "pw")
    active = django_user_model.objects.create_user("a@x.org", "pw", is_active=True)

    user_deactivate(_request(admin_user), active)
    active.refresh_from_db()
    assert active.is_active is False


def test_action_applicability_tracks_row_state(django_user_model):
    # Buttons are offered only when they'd change something: Approve on a
    # pending user, Deactivate on an active one — never both.
    from apps.console.actions import USER_ACTIONS

    by_slug = {a.slug: a for a in USER_ACTIONS}
    pending = django_user_model.objects.create_user("p@x.org", "pw")  # inactive
    active = django_user_model.objects.create_user("q@x.org", "pw", is_active=True)

    assert by_slug["approve"].applies(pending) is True
    assert by_slug["approve"].applies(active) is False
    assert by_slug["deactivate"].applies(active) is True
    assert by_slug["deactivate"].applies(pending) is False
