"""Feature B, Stage B3: assign enumerators to job units + 'My assignments'."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.fieldwork.models import CollectionUnit, Job, UnitAssignment
from apps.fieldwork.services import project_enumerators
from apps.projects.models import FormDefinition, Organization, Project
from apps.rbac.models import Membership, Role

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    uc = Project.objects.create(code="UC", name="UC", organization=org)
    form = FormDefinition.objects.create(project=uc, ona_form_id=1,
                                         role=FormDefinition.Role.VALIDATION)
    job = Job.objects.create(project=uc, name="Round 1", form=form, target_count=3)
    units = [CollectionUnit.objects.create(project=uc, code=f"HH{i}") for i in range(3)]
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True, organization=org)
    Membership.objects.create(user=coord, project=uc, role=Role.TRIAL_COORDINATOR)
    en = django_user_model.objects.create_user("en@x.org", "pw", full_name="Enid",
                                               is_active=True, organization=org)
    Membership.objects.create(user=en, project=uc, role=Role.ENUMERATOR)
    return {"uc": uc, "job": job, "units": units, "coord": coord, "en": en, "org": org}


def test_project_enumerators_lists_enumerator_role(world):
    pool = list(project_enumerators(world["uc"]))
    assert world["en"] in pool
    assert world["coord"] not in pool  # coordinator is not an enumerator


def test_assign_unit_to_enumerator(client, world):
    client.force_login(world["coord"])
    resp = client.post(reverse("console:job_assignments", args=[world["job"].pk]),
                       {"unit": str(world["units"][0].pk), "enumerator": str(world["en"].pk)})
    assert resp.status_code == 302
    a = UnitAssignment.objects.get(job=world["job"], unit=world["units"][0])
    assert a.enumerator == world["en"]
    assert world["en"] in world["job"].assigned_to.all()  # added to the job pool


def test_assign_all_remaining(client, world):
    client.force_login(world["coord"])
    client.post(reverse("console:job_assignments", args=[world["job"].pk]),
                {"action": "assign_all", "enumerator": str(world["en"].pk)})
    assert UnitAssignment.objects.filter(job=world["job"]).count() == 3


def test_remove_assignment(client, world):
    a = UnitAssignment.objects.create(job=world["job"], unit=world["units"][0],
                                      enumerator=world["en"])
    client.force_login(world["coord"])
    client.post(reverse("console:job_assignments", args=[world["job"].pk]),
                {"action": "remove", "assignment": str(a.pk)})
    assert not UnitAssignment.objects.filter(pk=a.pk).exists()


def test_assignments_scoped_to_own_project(client, django_user_model, world):
    """A coordinator can't open a job in a project they don't coordinate."""
    other_uc = Project.objects.create(code="OTHER", name="Other", organization=world["org"])
    other_job = Job.objects.create(project=other_uc, name="Other Job")
    client.force_login(world["coord"])
    assert client.get(reverse("console:job_assignments",
                              args=[other_job.pk])).status_code == 404


def test_my_assignments_lists_for_enumerator(client, world):
    UnitAssignment.objects.create(job=world["job"], unit=world["units"][0],
                                  enumerator=world["en"])
    client.force_login(world["en"])
    resp = client.get(reverse("dashboards:my_assignments"))
    assert resp.status_code == 200
    assert b"Round 1" in resp.content
    assert b"HH0" in resp.content


def test_my_assignments_only_mine(client, django_user_model, world):
    other = django_user_model.objects.create_user("o2@x.org", "pw", is_active=True)
    UnitAssignment.objects.create(job=world["job"], unit=world["units"][0], enumerator=other)
    client.force_login(world["en"])  # has no assignments
    resp = client.get(reverse("dashboards:my_assignments"))
    assert b"HH0" not in resp.content  # not assigned to me
