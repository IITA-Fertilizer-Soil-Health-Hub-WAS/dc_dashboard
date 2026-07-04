"""Projects directory + self-service access requests."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.projects.models import Country, Organization, Project, Region
from apps.rbac.models import Membership, ProjectAccessRequest, Role
from apps.rbac.permissions import visible_projects

pytestmark = pytest.mark.django_db


@pytest.fixture
def org_world(django_user_model):
    org = Organization.objects.create(code="org", name="Inst")
    region = Region.objects.create(organization=org, code="EA", name="East Africa")
    country = Country.objects.create(region=region, code="RW", name="Rwanda")
    uc_a = Project.objects.create(code="UC-A", name="Project A", organization=org, country=country)
    uc_b = Project.objects.create(code="UC-B", name="Project B", organization=org, country=country)

    member = django_user_model.objects.create_user("m@x.org", "pw", is_active=True, organization=org)
    Membership.objects.create(user=member, project=uc_a, role=Role.VIEWER)
    # A coordinator who administers UC-A (can approve requests on it).
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True, organization=org)
    Membership.objects.create(user=coord, country=country, role=Role.COUNTRY_COORDINATOR)
    return {"org": org, "uc_a": uc_a, "uc_b": uc_b, "member": member, "coord": coord}


def test_mine_shows_only_member_projects(client, org_world):
    client.force_login(org_world["member"])
    resp = client.get(reverse("dashboards:projects") + "?scope=mine")
    assert resp.status_code == 200
    assert b"UC-A" in resp.content       # member
    assert b"UC-B" not in resp.content   # not a member


def test_all_shows_directory_with_request_button(client, org_world):
    client.force_login(org_world["member"])
    resp = client.get(reverse("dashboards:projects") + "?scope=all")
    assert resp.status_code == 200
    assert b"UC-A" in resp.content and b"UC-B" in resp.content
    assert b"Request access" in resp.content  # for UC-B (non-member)


def test_filter_by_owner(client, django_user_model, org_world):
    # Owner is a real user relationship; the directory filters by it.
    owner = django_user_model.objects.create_user(
        "owner@x.org", "pw", is_active=True, full_name="Ada Owner",
        organization=org_world["org"],
    )
    org_world["uc_a"].owner = owner
    org_world["uc_a"].save(update_fields=["owner"])
    client.force_login(org_world["member"])
    resp = client.get(reverse("dashboards:projects") + f"?scope=all&owner={owner.user_id}")
    assert resp.status_code == 200
    assert b"UC-A" in resp.content       # owned by the filtered user
    assert b"UC-B" not in resp.content   # not theirs
    # The owner also appears as a filter option (rendered by name).
    assert b"Ada Owner" in resp.content


def test_request_form_renders(client, org_world):
    client.force_login(org_world["member"])
    resp = client.get(reverse("dashboards:project_request", args=["UC-B"]))
    assert resp.status_code == 200
    assert b"What do you intend to do" in resp.content


def test_request_access_creates_pending_with_intent(client, org_world):
    client.force_login(org_world["member"])
    resp = client.post(reverse("dashboards:project_request", args=["UC-B"]),
                       {"note": "Enumerator collecting data in Rwanda"})
    assert resp.status_code == 302
    req = ProjectAccessRequest.objects.get(
        user=org_world["member"], project=org_world["uc_b"],
        status=ProjectAccessRequest.Status.PENDING,
    )
    assert req.note == "Enumerator collecting data in Rwanda"


def test_request_requires_intent(client, org_world):
    client.force_login(org_world["member"])
    resp = client.post(reverse("dashboards:project_request", args=["UC-B"]), {"note": ""})
    assert resp.status_code == 200  # re-renders with an error, no request created
    assert b"Please describe" in resp.content
    assert not ProjectAccessRequest.objects.filter(project=org_world["uc_b"]).exists()


def test_request_existing_membership_is_noop(client, org_world):
    client.force_login(org_world["member"])
    client.post(reverse("dashboards:project_request", args=["UC-A"]))  # already a member
    assert not ProjectAccessRequest.objects.filter(project=org_world["uc_a"]).exists()


def test_catalogue_is_global_across_institutions(client, org_world):
    # Discovery is global: a member of one institution sees another's projects.
    other_org = Organization.objects.create(code="other", name="Other Inst")
    Project.objects.create(code="OTHER-UC", name="Other Project", organization=other_org)
    client.force_login(org_world["member"])
    resp = client.get(reverse("dashboards:projects") + "?scope=all")
    assert b"OTHER-UC" in resp.content


def test_can_request_open_project_in_other_org(client, django_user_model, org_world):
    # Cross-institution requests are allowed when the project is open.
    other_org = Organization.objects.create(code="other", name="Other")
    other_uc = Project.objects.create(code="OTHER-UC", name="Other", organization=other_org)
    client.force_login(org_world["member"])  # belongs to 'org'
    resp = client.post(reverse("dashboards:project_request", args=["OTHER-UC"]),
                       {"note": "Collaborating from another institution"})
    assert resp.status_code == 302
    assert ProjectAccessRequest.objects.filter(
        project=other_uc, user=org_world["member"]
    ).exists()


def test_cannot_request_closed_project(client, org_world):
    # A project closed to access requests refuses the request (inert card).
    closed = Project.objects.create(
        code="CLOSED-UC", name="Closed", organization=org_world["org"],
        allow_access_requests=False,
    )
    client.force_login(org_world["member"])
    resp = client.post(reverse("dashboards:project_request", args=["CLOSED-UC"]),
                       {"note": "let me in"})
    assert resp.status_code == 403
    assert not ProjectAccessRequest.objects.filter(project=closed).exists()


def test_closed_project_card_is_inert(client, org_world):
    Project.objects.create(
        code="CLOSED-UC", name="Closed Project", organization=org_world["org"],
        allow_access_requests=False,
    )
    client.force_login(org_world["member"])
    resp = client.get(reverse("dashboards:projects") + "?scope=all")
    html = resp.content.decode()
    assert "CLOSED-UC" in html                                   # still listed…
    assert "isn't accepting access requests" in html            # …but buttons disabled


def test_coordinator_approves_request_grants_access(client, org_world):
    member, uc_b, coord = org_world["member"], org_world["uc_b"], org_world["coord"]
    req = ProjectAccessRequest.objects.create(user=member, project=uc_b)
    client.force_login(coord)
    resp = client.post(reverse("dashboards:team_request_decision"), {
        "request": str(req.pk), "decision": "approve", "role": Role.ENUMERATOR,
    })
    assert resp.status_code == 302
    req.refresh_from_db()
    assert req.status == ProjectAccessRequest.Status.APPROVED
    assert Membership.objects.filter(
        user=member, project=uc_b, role=Role.ENUMERATOR
    ).exists()
    # The requester now sees the project.
    assert visible_projects(member).filter(pk=uc_b.pk).exists()


def test_coordinator_declines_request(client, org_world):
    member, uc_b, coord = org_world["member"], org_world["uc_b"], org_world["coord"]
    req = ProjectAccessRequest.objects.create(user=member, project=uc_b)
    client.force_login(coord)
    client.post(reverse("dashboards:team_request_decision"),
                {"request": str(req.pk), "decision": "decline"})
    req.refresh_from_db()
    assert req.status == ProjectAccessRequest.Status.DECLINED
    assert not Membership.objects.filter(user=member, project=uc_b).exists()


def test_request_outside_authority_not_listed(client, django_user_model, org_world):
    """A coordinator only sees requests for projects they administer."""
    member, uc_b = org_world["member"], org_world["uc_b"]
    ProjectAccessRequest.objects.create(user=member, project=uc_b)
    # A trial coordinator of a *different* project has no authority over UC-B.
    outsider = django_user_model.objects.create_user(
        "o@x.org", "pw", is_active=True, organization=org_world["org"]
    )
    Membership.objects.create(user=outsider, project=org_world["uc_a"],
                                     role=Role.TRIAL_COORDINATOR)
    client.force_login(outsider)
    resp = client.get(reverse("dashboards:team"))
    assert b"UC-B" not in resp.content  # the request is not theirs to action


def test_search_filters_projects(client, django_user_model, org_world):
    # A user with no memberships -> empty sidebar, so we only see the grid.
    browser = django_user_model.objects.create_user(
        "b@x.org", "pw", is_active=True, organization=org_world["org"]
    )
    client.force_login(browser)
    resp = client.get(reverse("dashboards:projects") + "?scope=all&q=Project B")
    assert b"UC-B" in resp.content
    assert b"UC-A" not in resp.content  # filtered out of the directory
