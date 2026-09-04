"""New users get read-only access to a demo project (if one exists) at signup, so
they land on something to explore instead of an empty 'request access' page."""
from __future__ import annotations

import pytest

from apps.accounts.services import grant_demo_access
from apps.projects.models import Project
from apps.rbac.models import Membership, Role

pytestmark = pytest.mark.django_db


def test_grants_viewer_on_latest_demo_project(django_user_model):
    Project.objects.create(code="DEMO-1", name="Demo soil project 1")
    demo2 = Project.objects.create(code="DEMO-2", name="Demo soil project 2")
    user = django_user_model.objects.create_user("new@x.org", "pw")

    assert grant_demo_access(user) is True
    m = Membership.objects.get(user=user, project=demo2)
    assert m.role == Role.VIEWER
    # Only the most recent demo is granted, not every DEMO-* project.
    assert not Membership.objects.filter(user=user, project__code="DEMO-1").exists()


def test_no_demo_project_is_a_graceful_noop(django_user_model):
    Project.objects.create(code="SNS-RWANDA", name="Real project")  # not a demo
    user = django_user_model.objects.create_user("new2@x.org", "pw")

    assert grant_demo_access(user) is False
    assert not Membership.objects.filter(user=user).exists()


def test_grant_is_idempotent(django_user_model):
    Project.objects.create(code="DEMO-1", name="Demo")
    user = django_user_model.objects.create_user("new3@x.org", "pw")

    assert grant_demo_access(user) is True
    assert grant_demo_access(user) is False          # already a member
    assert Membership.objects.filter(user=user, project__code="DEMO-1").count() == 1


def test_inactive_demo_project_is_skipped(django_user_model):
    Project.objects.create(code="DEMO-9", name="Retired demo", is_active=False)
    user = django_user_model.objects.create_user("new4@x.org", "pw")

    assert grant_demo_access(user) is False
    assert not Membership.objects.filter(user=user).exists()
