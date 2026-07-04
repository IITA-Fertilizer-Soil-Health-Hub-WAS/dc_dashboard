"""Health service delivery — Phase 1: programmes, client register, timeline.

Clients are CollectionUnits and encounters are Submissions viewed through a care
lens; these tests confirm the views scope correctly and render the record.
"""
from __future__ import annotations

from datetime import date

import pytest
from django.urls import reverse

from apps.care.models import CareProgram
from apps.fieldwork.models import CollectionUnit
from apps.projects.models import FormDefinition, Organization, Project
from apps.rbac.models import Membership, Role
from apps.submissions.models import Enumerator, Submission

pytestmark = pytest.mark.django_db


@pytest.fixture
def program(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    proj = Project.objects.create(code="NUTR", name="Nutrition follow-up", organization=org)
    prog = CareProgram.objects.create(project=proj, name="Nutrition", client_label="Patient")
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True, organization=org)
    Membership.objects.create(user=coord, project=proj, role=Role.TRIAL_COORDINATOR)
    unit = CollectionUnit.objects.create(project=proj, code="P001", name="Ada N", district="Gasabo")
    form = FormDefinition.objects.create(project=proj, ona_form_id=1,
                                         role=FormDefinition.Role.VALIDATION)
    en = Enumerator.objects.create(project=proj, enid="CHW1")
    for i, ev in enumerate(["Visit1", "Visit2"]):
        Submission.objects.create(project=proj, form=form, collection_unit=unit, enumerator=en,
                                  event_key=ev, event_date=date(2026, 1, 10 + i),
                                  ona_uuid=f"u{i}", content_hash="h")
    return {"prog": prog, "proj": proj, "coord": coord, "unit": unit}


def test_client_label_plural():
    assert CareProgram(client_label="Patient").client_label_plural == "Patients"
    assert CareProgram(client_label="Class").client_label_plural == "Classes"


def test_programs_list(client, program):
    client.force_login(program["coord"])
    resp = client.get(reverse("care:programs"))
    assert resp.status_code == 200
    assert b"Nutrition" in resp.content
    assert b"Patients" in resp.content  # client label pluralised


def test_client_register_counts_visits(client, program):
    client.force_login(program["coord"])
    resp = client.get(reverse("care:clients", args=["NUTR"]))
    assert resp.status_code == 200
    assert b"P001" in resp.content and b"Ada N" in resp.content
    # The unit shows its 2 encounters and the latest visit date.
    assert b"2026-01-11" in resp.content


def test_client_timeline_lists_encounters(client, program):
    client.force_login(program["coord"])
    resp = client.get(reverse("care:client_timeline",
                              args=["NUTR", program["unit"].pk]))
    assert resp.status_code == 200
    assert b"Visit1" in resp.content and b"Visit2" in resp.content
    assert b"CHW1" in resp.content  # enumerator on the encounter


def test_care_scoped_to_visible_projects(client, django_user_model, program):
    """A stranger with no access to the programme's project can't open it."""
    stranger = django_user_model.objects.create_user("s@x.org", "pw", is_active=True)
    client.force_login(stranger)
    assert client.get(reverse("care:clients", args=["NUTR"])).status_code == 404


def test_care_nav_hidden_without_a_programme(client, django_user_model):
    """The Care nav link only shows when a visible project is a care programme."""
    org = Organization.objects.create(code="o2", name="O2")
    proj = Project.objects.create(code="PLAIN", name="Plain", organization=org)
    u = django_user_model.objects.create_user("u@x.org", "pw", is_active=True, organization=org)
    Membership.objects.create(user=u, project=proj, role=Role.TRIAL_COORDINATOR)
    client.force_login(u)
    home = client.get(reverse("dashboards:index")).content
    assert reverse("care:programs").encode() not in home
