"""Ordinary members (viewers/enumerators) get read-only field data for their own
projects in the console — never editable, never another project's rows."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.console.registry import console_can_edit, console_key_allowed, grouped_for
from apps.rbac.models import Role, UseCaseMembership
from apps.submissions.models import Enumerator
from apps.usecases.models import Organization, Project

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    mine = Project.objects.create(code="MINE", name="Mine", organization=org)
    other = Project.objects.create(code="OTHER", name="Other", organization=org)
    Enumerator.objects.create(project=mine, enid="EN-MINE")
    Enumerator.objects.create(project=other, enid="EN-OTHER")
    viewer = django_user_model.objects.create_user("v@x.org", "pw", is_active=True, organization=org)
    UseCaseMembership.objects.create(user=viewer, project=mine, role=Role.VIEWER)
    stranger = django_user_model.objects.create_user("s@x.org", "pw", is_active=True, organization=org)
    return {"mine": mine, "other": other, "viewer": viewer, "stranger": stranger}


def test_member_may_view_field_data_but_not_edit(world):
    v = world["viewer"]
    assert console_key_allowed(v, "enumerators")        # field data: view ok
    assert not console_can_edit(v, "enumerators")       # but never edit
    assert console_key_allowed(v, "collection-units")
    assert not console_key_allowed(v, "forms")          # config stays coordinator+
    assert not console_key_allowed(v, "users")          # accounts stay staff


def test_member_with_no_projects_sees_nothing(world):
    assert not console_key_allowed(world["stranger"], "enumerators")
    assert grouped_for(world["stranger"]) == []


def test_member_field_data_list_scoped_to_their_project(client, world):
    client.force_login(world["viewer"])
    resp = client.get(reverse("console:list", args=["enumerators"]))
    assert resp.status_code == 200
    assert resp.context["can_edit"] is False           # read-only
    assert b"EN-MINE" in resp.content
    assert b"EN-OTHER" not in resp.content              # other project excluded


def test_member_cannot_open_edit_form(client, world):
    client.force_login(world["viewer"])
    en = world["mine"].enumerators.first()
    resp = client.get(reverse("console:edit", args=["enumerators", en.pk]))
    assert resp.status_code != 200                      # blocked from the edit screen


def test_member_reaches_field_data_via_workspace_not_console_groups(world):
    from apps.console.registry import console_key_allowed

    # Field data (enumerators, collection units) is reached from the project
    # workspace now, so a member has no console *groups* — but the sections stay
    # routable read-only (the workspace links point at them).
    assert dict(grouped_for(world["viewer"])) == {}
    assert console_key_allowed(world["viewer"], "collection-units")
    assert console_key_allowed(world["viewer"], "enumerators")
