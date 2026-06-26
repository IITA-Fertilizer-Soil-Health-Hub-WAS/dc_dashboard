"""Top-level Review hub: cross-project, gate-split, with inline actions."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.dashboards.review_hub import review_capability, review_todo_count
from apps.rbac.models import Role, UseCaseMembership
from apps.review import services
from apps.review.models import ReviewState
from apps.submissions.models import Submission
from apps.usecases.models import Country, FormDefinition, Organization, Region, UseCase

pytestmark = pytest.mark.django_db


def _sub(uc, n, state=ReviewState.INGESTED):
    form = FormDefinition.objects.create(use_case=uc, ona_form_id=n,
                                         role=FormDefinition.Role.VALIDATION)
    s = Submission.objects.create(use_case=uc, form=form, ona_uuid=f"u{uc.code}{n}",
                                  content_hash="h")
    r = s.review
    r.state = state
    r.save()
    return s


@pytest.fixture
def world(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    region = Region.objects.create(organization=org, code="EA", name="EA")
    country = Country.objects.create(region=region, code="RW", name="Rwanda")
    uc1 = UseCase.objects.create(code="UC1", name="One", organization=org, country=country)
    uc2 = UseCase.objects.create(code="UC2", name="Two", organization=org, country=country)

    tc = django_user_model.objects.create_user("tc@x.org", "pw", is_active=True, organization=org)
    UseCaseMembership.objects.create(user=tc, use_case=uc1, role=Role.TRIAL_COORDINATOR)
    regional = django_user_model.objects.create_user("rc@x.org", "pw", is_active=True, organization=org)
    UseCaseMembership.objects.create(user=regional, region=region, role=Role.REGIONAL_COORDINATOR)
    return {"uc1": uc1, "uc2": uc2, "tc": tc, "regional": regional, "country": country, "region": region}


def test_capability_gate_split(world):
    g1, g2 = review_capability(world["tc"])
    assert world["uc1"].id in g1  # trial coordinator endorses uc1
    assert not g2                  # not a validator
    rg1, rg2 = review_capability(world["regional"])
    assert {world["uc1"].id, world["uc2"].id} <= rg2  # regional validates both
    assert not rg1                 # regional does not endorse (Gate 1)


def test_endorse_section_for_gate1(client, world):
    _sub(world["uc1"], 1, ReviewState.IN_REVIEW)
    client.force_login(world["tc"])
    resp = client.get(reverse("dashboards:review_hub"))
    assert resp.status_code == 200
    assert b"Awaiting your endorsement" in resp.content
    assert b"UC1" in resp.content


def test_validate_section_for_gate2(client, world):
    s = _sub(world["uc1"], 1, ReviewState.QC_PENDING)
    client.force_login(world["regional"])
    resp = client.get(reverse("dashboards:review_hub"))
    assert b"Awaiting your validation" in resp.content
    assert str(s.use_case.code).encode() in resp.content


def test_todo_count(world):
    _sub(world["uc1"], 1, ReviewState.IN_REVIEW)
    _sub(world["uc1"], 2, ReviewState.QC_PENDING)
    assert review_todo_count(world["tc"]) == 1       # only the endorse-able one
    assert review_todo_count(world["regional"]) == 1  # only the QC_PENDING one


def test_hub_action_endorse(client, world):
    s = _sub(world["uc1"], 1, ReviewState.IN_REVIEW)
    client.force_login(world["tc"])
    resp = client.post(reverse("dashboards:review_hub_action"),
                       {"submission": str(s.id), "action": "ENDORSE"})
    assert resp.status_code == 302
    s.refresh_from_db()
    assert s.review.state == ReviewState.QC_PENDING


def test_hub_action_validate(client, world):
    s = _sub(world["uc1"], 1, ReviewState.IN_REVIEW)
    services.endorse(world["tc"], s)  # Gate 1 first
    client.force_login(world["regional"])
    resp = client.post(reverse("dashboards:review_hub_action"),
                       {"submission": str(s.id), "action": "QC_APPROVE"})
    assert resp.status_code == 302
    s.refresh_from_db()
    assert s.review.state == ReviewState.APPROVED


def test_hub_action_blocked_outside_projects(client, django_user_model, world):
    s = _sub(world["uc2"], 1, ReviewState.IN_REVIEW)  # tc has no access to uc2
    client.force_login(world["tc"])
    resp = client.post(reverse("dashboards:review_hub_action"),
                       {"submission": str(s.id), "action": "ENDORSE"})
    assert resp.status_code == 403
    s.refresh_from_db()
    assert s.review.state == ReviewState.IN_REVIEW


def test_viewer_has_no_review_todo(django_user_model, world):
    viewer = django_user_model.objects.create_user("v@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=viewer, use_case=world["uc1"], role=Role.VIEWER)
    _sub(world["uc1"], 1, ReviewState.IN_REVIEW)
    assert review_todo_count(viewer) == 0
