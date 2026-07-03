"""Phase 9 cutover tests: eia_apps -> memberships, and the Auth0 claim snapshot."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.core.management import call_command

from apps.accounts.adapters import SocialAccountAdapter
from apps.projects.models import Project
from apps.rbac.models import ProjectMembership, Role

pytestmark = pytest.mark.django_db


def test_migrate_eia_apps_creates_viewer_memberships(django_user_model):
    rwanda = Project.objects.create(code="SNS-RWANDA", name="SNS Rwanda")
    kalro = Project.objects.create(code="KALRO", name="KALRO")
    user = django_user_model.objects.create_user(
        "u@x.org", "pw", is_active=True,
        legacy_eia_apps={"SNS-RWANDA": {}, "KALRO": {}, "GHOST-UC": {}},
    )

    call_command("migrate_eia_apps")

    roles = set(
        ProjectMembership.objects.filter(user=user).values_list("project__code", "role")
    )
    assert (rwanda.code, Role.VIEWER) in roles
    assert (kalro.code, Role.VIEWER) in roles
    # Unknown project is skipped, not created.
    assert not ProjectMembership.objects.filter(project__code="GHOST-UC").exists()


def test_migrate_eia_apps_idempotent(django_user_model):
    Project.objects.create(code="SNS-RWANDA", name="SNS Rwanda")
    user = django_user_model.objects.create_user(
        "u@x.org", "pw", is_active=True, legacy_eia_apps={"SNS-RWANDA": {}}
    )
    call_command("migrate_eia_apps")
    call_command("migrate_eia_apps")
    assert ProjectMembership.objects.filter(user=user).count() == 1


def test_dry_run_creates_nothing(django_user_model):
    Project.objects.create(code="SNS-RWANDA", name="SNS Rwanda")
    user = django_user_model.objects.create_user(
        "u@x.org", "pw", is_active=True, legacy_eia_apps={"SNS-RWANDA": {}}
    )
    call_command("migrate_eia_apps", "--dry-run")
    assert ProjectMembership.objects.filter(user=user).count() == 0


def test_social_adapter_snapshots_auth0_claims(django_user_model):
    user = django_user_model.objects.create_user("u@x.org", "pw", is_active=True)
    sociallogin = SimpleNamespace(
        user=user,
        account=SimpleNamespace(
            extra_data={"sub": "auth0|abc123", "eia_apps": {"SNS-RWANDA": {}, "KALRO": {}}}
        ),
    )
    SocialAccountAdapter().pre_social_login(request=None, sociallogin=sociallogin)

    user.refresh_from_db()
    assert user.auth0_sub == "auth0|abc123"
    assert user.legacy_eia_apps == {"SNS-RWANDA": {}, "KALRO": {}}
