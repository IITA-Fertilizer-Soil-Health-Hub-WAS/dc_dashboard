"""Care Phase 3: worker caseload, assignment, and referral (reassignment)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.urls import reverse

from apps.care.models import CareAssignment, CareProgram
from apps.care.services import assign_client, worker_caseload
from apps.fieldwork.models import CollectionUnit
from apps.projects.models import EventScheduleItem, FormDefinition, Organization, Project
from apps.rbac.models import Membership, Role
from apps.submissions.models import Submission

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    proj = Project.objects.create(code="EXT", name="Extension", organization=org)
    prog = CareProgram.objects.create(project=proj, client_label="Farmer")
    EventScheduleItem.objects.create(project=proj, event_key="Event1", sequence=1,
                                     anchor="SITE_SELECTION", offset_days=14, grace_days=3)
    EventScheduleItem.objects.create(project=proj, event_key="Event2", sequence=2,
                                     anchor="SITE_SELECTION", offset_days=45, grace_days=3)
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True, organization=org)
    Membership.objects.create(user=coord, project=proj, role=Role.TRIAL_COORDINATOR)
    w1 = django_user_model.objects.create_user("w1@x.org", "pw", is_active=True,
                                               full_name="Worker One", organization=org)
    w2 = django_user_model.objects.create_user("w2@x.org", "pw", is_active=True,
                                               full_name="Worker Two", organization=org)
    Membership.objects.create(user=w1, project=proj, role=Role.ENUMERATOR)
    Membership.objects.create(user=w2, project=proj, role=Role.ENUMERATOR)
    anchor = date.today() - timedelta(days=60)
    unit = CollectionUnit.objects.create(project=proj, code="FRM001", site_selection_date=anchor)
    form = FormDefinition.objects.create(project=proj, ona_form_id=1,
                                         role=FormDefinition.Role.VALIDATION)
    Submission.objects.create(project=proj, form=form, collection_unit=unit, event_key="Event1",
                              event_date=anchor + timedelta(days=14), ona_uuid="e1", content_hash="h")
    return {"prog": prog, "proj": proj, "coord": coord, "w1": w1, "w2": w2, "unit": unit}


def test_assign_then_refer_keeps_chain(world):
    a1 = assign_client(world["prog"], world["unit"], world["w1"], by=world["coord"])
    a2 = assign_client(world["prog"], world["unit"], world["w2"], by=world["coord"],
                       note="Worker One on leave")
    a1.refresh_from_db()
    assert a1.is_active is False and a2.is_active is True
    # Exactly one active assignment; the history row survives (referral trail).
    assert CareAssignment.objects.filter(unit=world["unit"]).count() == 2
    assert list(worker_caseload(world["w1"])) == []
    assert [a.unit_id for a in worker_caseload(world["w2"])] == [world["unit"].id]


def test_assign_view_creates_assignment(client, world):
    client.force_login(world["coord"])
    resp = client.post(reverse("care:assign", args=["EXT"]),
                       {"unit": str(world["unit"].pk), "worker": str(world["w1"].pk)})
    assert resp.status_code == 302
    assert CareAssignment.objects.filter(unit=world["unit"], worker=world["w1"], is_active=True).exists()


def test_my_caseload_shows_overdue_task(client, world):
    assign_client(world["prog"], world["unit"], world["w1"], by=world["coord"])
    client.force_login(world["w1"])
    resp = client.get(reverse("care:my_caseload"))
    assert resp.status_code == 200
    assert b"FRM001" in resp.content
    # Event2 is overdue (past +45, not done) -> flagged on the caseload.
    assert b"overdue" in resp.content


def test_caseload_nav_appears_for_assigned_worker(client, world):
    assign_client(world["prog"], world["unit"], world["w2"], by=world["coord"])
    # The sidebar (rendered on every authenticated page) shows the caseload link.
    url = reverse("care:my_caseload").encode()
    client.force_login(world["w2"])
    assert url in client.get(reverse("care:my_caseload")).content  # nav link present
    # A worker with no caseload doesn't get the nav link.
    client.force_login(world["w1"])
    assert url not in client.get(reverse("care:my_caseload")).content


def test_register_shows_assign_control_for_coordinator(client, world):
    client.force_login(world["coord"])
    html = client.get(reverse("care:clients", args=["EXT"])).content
    assert b"Worker One" in html and b'name="worker"' in html
