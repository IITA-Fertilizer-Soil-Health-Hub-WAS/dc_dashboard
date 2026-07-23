"""The role-aware, progress-driven getting-started checklist."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.dashboards.getting_started import getting_started
from apps.projects.models import Organization, Project
from apps.rbac.models import Membership, Role
from apps.validation.models import ValidationRule

pytestmark = pytest.mark.django_db


def _item(gs, prefix):
    return next(i for i in gs["items"] if i["label"].startswith(prefix))


def test_admin_checklist_tracks_real_state(django_user_model):
    admin = django_user_model.objects.create_superuser("a@x.org", "pw")
    gs = getting_started(admin, None)
    assert gs["title"] == "Set up the platform"
    assert not _item(gs, "Create an institution")["done"]  # nothing set up yet
    Organization.objects.create(code="o", name="O")
    assert _item(getting_started(admin, None), "Create an institution")["done"]


def test_project_checklist_flips_as_you_configure(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    p = Project.objects.create(code="P", name="P", organization=org)
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True,
                                                  organization=org)
    Membership.objects.create(user=coord, project=p, role=Role.TRIAL_COORDINATOR)

    gs = getting_started(coord, p)
    assert gs["title"] == "Getting started"
    assert not _item(gs, "Add a validation rule")["done"]

    ValidationRule.objects.create(project=p, code="r", rule_type="UNIQUE_FIELD",
                                  params={"field": "x"})
    assert _item(getting_started(coord, p), "Add a validation rule")["done"]


def test_enumerator_gets_no_checklist(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    p = Project.objects.create(code="P", name="P", organization=org)
    en = django_user_model.objects.create_user("e@x.org", "pw", is_active=True)
    Membership.objects.create(user=en, project=p, role=Role.ENUMERATOR)
    # Enumerators don't manage setup — no checklist for them.
    assert getting_started(en, p) is None


def test_home_page_shows_admin_checklist(client, django_user_model):
    admin = django_user_model.objects.create_superuser("a@x.org", "pw")
    client.force_login(admin)
    body = client.get(reverse("dashboards:index")).content.decode()
    assert "Set up the platform" in body and "Onboard the first project" in body
