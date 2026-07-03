"""Coordinators get Write-back / Link-enumerators / Access-requests, scoped to
their own projects — and ordinary members can't reach the operational tools."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.rbac.models import Role, UseCaseMembership
from apps.submissions.linking import link_enumerators
from apps.submissions.models import Enumerator, Submission
from apps.usecases.models import FormDefinition, Organization, Project

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    mine = Project.objects.create(code="MINE", name="Mine", organization=org)
    other = Project.objects.create(code="OTHER", name="Other", organization=org)
    fm = FormDefinition.objects.create(project=mine, ona_form_id=1, role=FormDefinition.Role.VALIDATION)
    fo = FormDefinition.objects.create(project=other, ona_form_id=2, role=FormDefinition.Role.VALIDATION)
    pend = Submission.WriteBackStatus.PENDING
    Submission.objects.create(project=mine, form=fm, ona_uuid="m1", content_hash="h", writeback_status=pend)
    Submission.objects.create(project=other, form=fo, ona_uuid="o1", content_hash="h", writeback_status=pend)
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True, organization=org)
    UseCaseMembership.objects.create(user=coord, project=mine, role=Role.TRIAL_COORDINATOR)
    viewer = django_user_model.objects.create_user("v@x.org", "pw", is_active=True, organization=org)
    UseCaseMembership.objects.create(user=viewer, project=mine, role=Role.VIEWER)
    return {"mine": mine, "other": other, "coord": coord, "viewer": viewer}


def test_writeback_scoped_to_coordinator_projects(client, world):
    client.force_login(world["coord"])
    resp = client.get(reverse("console:writeback"))
    assert resp.status_code == 200
    # Only the coordinator's own project's pending item is in the queue.
    assert resp.context["pending"] == 1
    assert b"MINE" in resp.content
    assert b"OTHER" not in resp.content


def test_writeback_blocked_for_plain_member(client, world):
    client.force_login(world["viewer"])
    resp = client.get(reverse("console:writeback"))
    assert resp.status_code != 200  # redirected / forbidden, never the queue


def test_link_enumerators_scoped(world):
    Enumerator.objects.create(project=world["mine"], enid="EN-MINE")
    Enumerator.objects.create(project=world["other"], enid="EN-OTHER")
    report = link_enumerators(apply=False, projects=[world["mine"].id])
    codes = {p.project for p in report.proposals}
    assert codes == {"MINE"}  # the other project's enumerator is out of scope


def test_access_requests_not_a_coordinator_console_section(client, world):
    # Access requests are handled in 'Team & access', so the raw console section
    # stays staff-only — coordinators don't get a duplicate of it.
    client.force_login(world["coord"])
    resp = client.get(reverse("console:list", args=["access-requests"]))
    assert resp.status_code != 200


def test_access_requests_blocked_for_member(client, world):
    client.force_login(world["viewer"])
    resp = client.get(reverse("console:list", args=["access-requests"]))
    assert resp.status_code != 200
