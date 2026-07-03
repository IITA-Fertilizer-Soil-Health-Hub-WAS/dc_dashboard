"""Per-project Review tab: gate-split queue with inline endorse/validate/decline."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.projects.models import Country, FormDefinition, Organization, Project, Region
from apps.rbac.models import ProjectMembership, Role
from apps.review import services
from apps.review.models import ReviewState
from apps.submissions.models import Submission

pytestmark = pytest.mark.django_db


def _sub(uc, n, state=ReviewState.INGESTED):
    form = FormDefinition.objects.create(project=uc, ona_form_id=n,
                                         role=FormDefinition.Role.VALIDATION)
    s = Submission.objects.create(project=uc, form=form, ona_uuid=f"u{n}", content_hash="h")
    r = s.review
    r.state = state
    r.save()
    return s


@pytest.fixture
def world(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    region = Region.objects.create(organization=org, code="EA", name="EA")
    country = Country.objects.create(region=region, code="RW", name="Rwanda")
    uc = Project.objects.create(code="UC", name="UC", organization=org, country=country)

    tc = django_user_model.objects.create_user("tc@x.org", "pw", is_active=True, organization=org)
    ProjectMembership.objects.create(user=tc, project=uc, role=Role.TRIAL_COORDINATOR)
    regional = django_user_model.objects.create_user("rc@x.org", "pw", is_active=True, organization=org)
    ProjectMembership.objects.create(user=regional, region=region, role=Role.REGIONAL_COORDINATOR)
    viewer = django_user_model.objects.create_user("v@x.org", "pw", is_active=True, organization=org)
    ProjectMembership.objects.create(user=viewer, project=uc, role=Role.VIEWER)
    return {"uc": uc, "tc": tc, "regional": regional, "viewer": viewer}


def test_review_tab_shows_endorse_for_gate1(client, world):
    _sub(world["uc"], 1, ReviewState.IN_REVIEW)
    client.force_login(world["tc"])
    resp = client.get(reverse("dashboards:tab_review", args=[world["uc"].code]))
    assert resp.status_code == 200
    assert b"Awaiting your endorsement" in resp.content
    assert b"Endorse" in resp.content
    assert b"Awaiting your validation" not in resp.content  # tc is not a validator


def test_review_tab_shows_validate_for_gate2(client, world):
    _sub(world["uc"], 1, ReviewState.QC_PENDING)
    client.force_login(world["regional"])
    resp = client.get(reverse("dashboards:tab_review", args=[world["uc"].code]))
    assert b"Awaiting your validation" in resp.content
    assert b"Validate" in resp.content


def test_review_tab_readonly_for_viewer(client, world):
    _sub(world["uc"], 1, ReviewState.IN_REVIEW)
    client.force_login(world["viewer"])
    resp = client.get(reverse("dashboards:tab_review", args=[world["uc"].code]))
    assert resp.status_code == 200
    assert b"read-only access" in resp.content
    assert b"Endorse" not in resp.content


def test_review_tab_action_endorse(client, world):
    s = _sub(world["uc"], 1, ReviewState.IN_REVIEW)
    client.force_login(world["tc"])
    resp = client.post(reverse("dashboards:tab_review_action", args=[world["uc"].code]),
                       {"submission": str(s.id), "action": "ENDORSE"})
    assert resp.status_code == 200  # returns refreshed tab partial
    s.refresh_from_db()
    assert s.review.state == ReviewState.QC_PENDING


def test_review_tab_action_validate(client, world):
    s = _sub(world["uc"], 1, ReviewState.IN_REVIEW)
    services.endorse(world["tc"], s)  # Gate 1
    client.force_login(world["regional"])
    client.post(reverse("dashboards:tab_review_action", args=[world["uc"].code]),
                {"submission": str(s.id), "action": "QC_APPROVE"})
    s.refresh_from_db()
    assert s.review.state == ReviewState.APPROVED


def test_review_action_scoped_to_project(client, django_user_model, world):
    """A submission in another project can't be actioned through this project's tab."""
    other = Project.objects.create(code="OTHER", name="Other")
    s = _sub(other, 1, ReviewState.IN_REVIEW)
    client.force_login(world["tc"])
    # tc has no access to OTHER; posting its id under UC's tab must not act.
    client.post(reverse("dashboards:tab_review_action", args=[world["uc"].code]),
                {"submission": str(s.id), "action": "ENDORSE"})
    s.refresh_from_db()
    assert s.review.state == ReviewState.IN_REVIEW


def test_project_page_loads_selected_section(client, world):
    # The sidebar is the single nav; the page loads only the chosen section's
    # content (?tab=review → the review partial URL), not a full tab bar.
    client.force_login(world["tc"])
    resp = client.get(reverse("dashboards:project", args=[world["uc"].code]), {"tab": "review"})
    assert resp.status_code == 200
    assert reverse("dashboards:tab_review", args=[world["uc"].code]).encode() in resp.content
    # Default (no tab) loads Summary, not Review.
    home = client.get(reverse("dashboards:project", args=[world["uc"].code]))
    assert reverse("dashboards:tab_summary", args=[world["uc"].code]).encode() in home.content
    assert reverse("dashboards:tab_review", args=[world["uc"].code]).encode() not in home.content
