"""Coordinators get a read-only, scoped console (their projects' config + field
data); everything else stays hub-operator (staff) only."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.console.registry import console_key_allowed, grouped_for
from apps.projects.models import Country, FormDefinition, Organization, Project, Region
from apps.rbac.models import Role, UseCaseMembership
from apps.submissions.models import Enumerator

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    region = Region.objects.create(organization=org, code="EA", name="EA")
    country = Country.objects.create(region=region, code="RW", name="Rwanda")
    mine = Project.objects.create(code="MINE", name="Mine", organization=org, country=country)
    other = Project.objects.create(code="OTHER", name="Other", organization=org, country=country)
    FormDefinition.objects.create(project=mine, ona_form_id=1, role=FormDefinition.Role.VALIDATION)
    FormDefinition.objects.create(project=other, ona_form_id=2, role=FormDefinition.Role.VALIDATION)
    Enumerator.objects.create(project=mine, enid="EN-MINE")
    Enumerator.objects.create(project=other, enid="EN-OTHER")

    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True, organization=org)
    UseCaseMembership.objects.create(user=coord, project=mine, role=Role.TRIAL_COORDINATOR)
    viewer = django_user_model.objects.create_user("v@x.org", "pw", is_active=True, organization=org)
    UseCaseMembership.objects.create(user=viewer, project=mine, role=Role.VIEWER)
    staff = django_user_model.objects.create_superuser("a@x.org", "pw")
    return {"mine": mine, "other": other, "coord": coord, "viewer": viewer, "staff": staff}


def test_console_key_allowed_matrix(world):
    coord, viewer, staff = world["coord"], world["viewer"], world["staff"]
    assert console_key_allowed(coord, "forms")          # config: yes
    assert console_key_allowed(coord, "enumerators")    # field data: yes
    assert not console_key_allowed(coord, "organizations")  # tenancy: no
    assert not console_key_allowed(coord, "users")          # identity: no
    assert not console_key_allowed(viewer, "forms")         # viewer: no console
    assert console_key_allowed(staff, "organizations")      # staff: everything


def test_grouped_for_coordinator_is_scoped_subset(world):
    groups = dict(grouped_for(world["coord"]))
    # Coordinators see only their projects' config / field data / monitoring —
    # never tenancy, geography, or the accounts & roles registry (access is the
    # Team & access screen, not a console section).
    assert set(groups) <= {"Configuration", "Field data", "Monitoring"}
    assert "Tenancy" not in groups and "Geography" not in groups
    assert "Accounts & roles" not in groups
    # Staff get the full set.
    assert "Tenancy" in dict(grouped_for(world["staff"]))


def test_coordinator_sees_only_their_projects_forms(client, world):
    client.force_login(world["coord"])
    resp = client.get(reverse("console:list", args=["forms"]))
    assert resp.status_code == 200
    # Scoped: only the coordinator's project appears.
    assert b"MINE" in resp.content
    assert b"OTHER" not in resp.content


def test_coordinator_field_data_scoped(client, world):
    client.force_login(world["coord"])
    resp = client.get(reverse("console:list", args=["enumerators"]))
    assert resp.status_code == 200
    assert b"EN-MINE" in resp.content
    assert b"EN-OTHER" not in resp.content


def test_coordinator_has_edit_buttons(client, world):
    client.force_login(world["coord"])
    resp = client.get(reverse("console:list", args=["forms"]))
    assert b"+ New" in resp.content
    assert reverse("console:create", args=["forms"]).encode() in resp.content


def test_coordinator_cannot_open_staff_only_section(client, world):
    client.force_login(world["coord"])
    assert client.get(reverse("console:list", args=["organizations"])).status_code == 403
    assert client.get(reverse("console:list", args=["users"])).status_code == 403


def test_coordinator_create_form_only_offers_own_project(client, world):
    client.force_login(world["coord"])
    resp = client.get(reverse("console:create", args=["forms"]))
    assert resp.status_code == 200
    # The project choices are scoped to their project, not OTHER.
    assert b"MINE" in resp.content
    assert b"OTHER" not in resp.content


def test_coordinator_can_create_in_own_project(client, world):
    client.force_login(world["coord"])
    resp = client.post(reverse("console:create", args=["crops"]),
                       {"project": str(world["mine"].pk), "name": "maize", "aliases": "[]"})
    assert resp.status_code == 302
    from apps.projects.models import Crop
    assert Crop.objects.filter(project=world["mine"], name="maize").exists()


def test_coordinator_cannot_create_in_other_project(client, world):
    client.force_login(world["coord"])
    resp = client.post(reverse("console:create", args=["crops"]),
                       {"project": str(world["other"].pk), "name": "rice", "aliases": "[]"})
    assert resp.status_code == 200  # re-renders: project not an allowed choice
    from apps.projects.models import Crop
    assert not Crop.objects.filter(project=world["other"]).exists()


def test_coordinator_cannot_edit_other_project_object(client, world):
    other_form = world["other"].forms.first()
    client.force_login(world["coord"])
    assert client.get(reverse("console:edit", args=["forms", other_form.pk])).status_code == 404
    assert client.get(reverse("console:delete", args=["forms", other_form.pk])).status_code == 404


def test_coordinator_can_edit_own_object(client, world):
    my_form = world["mine"].forms.first()
    client.force_login(world["coord"])
    assert client.get(reverse("console:edit", args=["forms", my_form.pk])).status_code == 200


def test_coordinator_cannot_mutate_readonly_section(client, world):
    """Submissions stay read-only even though they're in a coordinator's scope."""
    client.force_login(world["coord"])
    assert client.get(reverse("console:create", args=["submissions"])).status_code == 403


def test_viewer_has_read_only_field_data_only(client, world):
    client.force_login(world["viewer"])
    # No configuration access (config stays coordinator+)...
    assert client.get(reverse("console:list", args=["forms"])).status_code == 403
    # ...but at most read-only field data for their own projects — never config.
    groups = dict(grouped_for(world["viewer"]))
    assert set(groups) <= {"Field data"}


