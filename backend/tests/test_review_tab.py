"""Per-project Review tab: gate-split queue with inline endorse/validate/decline."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.projects.models import Country, FormDefinition, Organization, Project, Region
from apps.rbac.models import Membership, Role
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
    Membership.objects.create(user=tc, project=uc, role=Role.TRIAL_COORDINATOR)
    regional = django_user_model.objects.create_user("rc@x.org", "pw", is_active=True, organization=org)
    Membership.objects.create(user=regional, region=region, role=Role.REGIONAL_COORDINATOR)
    viewer = django_user_model.objects.create_user("v@x.org", "pw", is_active=True, organization=org)
    Membership.objects.create(user=viewer, project=uc, role=Role.VIEWER)
    return {"uc": uc, "tc": tc, "regional": regional, "viewer": viewer}


def test_review_tab_shows_endorse_for_gate1(client, world):
    _sub(world["uc"], 1, ReviewState.IN_REVIEW)   # opened → the 'In progress' pool
    client.force_login(world["tc"])
    resp = client.get(reverse("dashboards:tab_review", args=[world["uc"].code]))
    assert resp.status_code == 200
    assert b"In progress" in resp.content
    assert b"Endorse" in resp.content
    assert b"Awaiting your validation" not in resp.content  # tc is not a validator


def test_review_queue_splits_by_pipeline_stage(client, world):
    """Each submission sits in exactly one pool by state, so an item leaves the
    'to do' pull the moment it's acted on. Edit-requested is view-only (the ball
    is with the enumerator) — no Endorse/Decline offered there."""
    _sub(world["uc"], 1, ReviewState.INGESTED)        # Needs review
    _sub(world["uc"], 2, ReviewState.IN_REVIEW)       # In progress
    _sub(world["uc"], 3, ReviewState.EDIT_REQUESTED)  # Waiting on enumerator
    client.force_login(world["tc"])
    resp = client.get(reverse("dashboards:tab_review", args=[world["uc"].code]))
    body = resp.content.decode()
    for pool in ("Needs review", "In progress", "Waiting on enumerator"):
        assert pool in body
    # The waiting pool (its section is marked by the hourglass icon, last on the
    # page) is view-only: the row offers Review but no inline action buttons.
    row = body.split("hourglass_empty", 1)[1]
    assert "Review" in row
    assert "ENDORSE" not in row and "DECLINE" not in row


def test_summary_and_me_mirror_the_review_pipeline(client, world):
    """The Summary health panel and M&E report the same pipeline buckets as the
    Review queue (one submission, one stage), so the numbers always agree."""
    from apps.kpi.metrics import project_metrics

    _sub(world["uc"], 1, ReviewState.INGESTED)        # needs_review
    _sub(world["uc"], 2, ReviewState.IN_REVIEW)       # in_progress
    _sub(world["uc"], 3, ReviewState.EDIT_REQUESTED)  # waiting
    _sub(world["uc"], 4, ReviewState.QC_PENDING)      # awaiting_validation
    client.force_login(world["tc"])

    body = client.get(reverse("dashboards:tab_summary", args=[world["uc"].code])).content.decode()
    for label in ("Needs review", "In progress", "Waiting on enumerator", "Awaiting validation"):
        assert label in body

    m = project_metrics(world["uc"], "30")
    assert m["needs_review"] == 1 and m["in_progress"] == 1
    assert m["waiting"] == 1 and m["awaiting_validation"] == 1


def test_review_tab_shows_validate_for_gate2(client, world):
    _sub(world["uc"], 1, ReviewState.QC_PENDING)
    client.force_login(world["regional"])
    resp = client.get(reverse("dashboards:tab_review", args=[world["uc"].code]))
    assert b"Awaiting your validation" in resp.content
    assert b"Approve" in resp.content   # Gate-2 forward action, renamed from 'Validate'


def test_contextual_config_links(client, world):
    # Rejection reasons sit with Review; validation Rules sit with Issues —
    # coordinators get a link to each from the screen it powers; viewers don't.
    uc = world["uc"]
    client.force_login(world["tc"])
    rev = client.get(reverse("dashboards:tab_review", args=[uc.code])).content
    iss = client.get(reverse("dashboards:tab_issues", args=[uc.code])).content
    assert f"/manage/rejection-reasons/?project={uc.code}".encode() in rev
    assert f"/manage/validation-rules/?project={uc.code}".encode() in iss

    client.force_login(world["viewer"])
    iss_v = client.get(reverse("dashboards:tab_issues", args=[uc.code])).content
    assert b"/manage/validation-rules/" not in iss_v   # read-only viewer: no config link


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
