"""Tenant isolation: one institution can never see or touch another's data."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.projects.models import Country, Organization, Project, Region
from apps.projects.tenancy import default_organization, resolve_organization
from apps.rbac.models import Membership, Role
from apps.rbac.permissions import organization_of, visible_projects

pytestmark = pytest.mark.django_db


@pytest.fixture
def two_orgs(django_user_model):
    a = Organization.objects.create(code="org-a", name="Institution A")
    b = Organization.objects.create(code="org-b", name="Institution B")
    ra = Region.objects.create(organization=a, code="EA", name="East Africa")
    rb = Region.objects.create(organization=b, code="WA", name="West Africa")
    ca = Country.objects.create(region=ra, code="RW", name="Rwanda")
    cb = Country.objects.create(region=rb, code="NG", name="Nigeria")
    uca = Project.objects.create(code="A-SNS", name="A SNS", organization=a, country=ca)
    ucb = Project.objects.create(code="B-BIO", name="B BioSSA", organization=b, country=cb)

    coord_a = django_user_model.objects.create_user("a@x.org", "pw", is_active=True, organization=a)
    Membership.objects.create(user=coord_a, country=ca, role=Role.COUNTRY_COORDINATOR)
    coord_b = django_user_model.objects.create_user("b@x.org", "pw", is_active=True, organization=b)
    Membership.objects.create(user=coord_b, country=cb, role=Role.COUNTRY_COORDINATOR)
    return {
        "a": a, "b": b, "ra": ra, "rb": rb, "ca": ca, "cb": cb,
        "uca": uca, "ucb": ucb, "coord_a": coord_a, "coord_b": coord_b,
    }


def test_visible_projects_isolated(two_orgs):
    a_codes = set(visible_projects(two_orgs["coord_a"]).values_list("code", flat=True))
    b_codes = set(visible_projects(two_orgs["coord_b"]).values_list("code", flat=True))
    assert a_codes == {"A-SNS"}
    assert b_codes == {"B-BIO"}


def test_cannot_open_other_orgs_project(client, two_orgs):
    client.force_login(two_orgs["coord_a"])
    resp = client.get(reverse("dashboards:project", args=[two_orgs["ucb"].code]))
    assert resp.status_code == 404  # B's project is invisible to A


def test_hub_operator_spans_all_orgs(django_user_model, two_orgs):
    hub = django_user_model.objects.create_superuser("hub@x.org", "pw")  # no organization
    codes = set(visible_projects(hub).values_list("code", flat=True))
    assert codes == {"A-SNS", "B-BIO"}


def test_organization_of_resolves_scope(two_orgs):
    assert organization_of(two_orgs["uca"]) == two_orgs["a"].id
    assert organization_of(two_orgs["ca"]) == two_orgs["a"].id
    assert organization_of(two_orgs["ra"]) == two_orgs["a"].id


def test_team_active_users_scoped_to_org(client, two_orgs):
    client.force_login(two_orgs["coord_a"])
    resp = client.get(reverse("dashboards:team"))
    assert resp.status_code == 200
    assert b"a@x.org" in resp.content
    assert b"b@x.org" not in resp.content  # B's people are not listed for A


def test_cannot_grant_to_other_orgs_user(client, two_orgs):
    """A coordinator in A cannot attach B's existing user to A's data."""
    client.force_login(two_orgs["coord_a"])
    resp = client.post(reverse("dashboards:team_grant"), {
        "user": str(two_orgs["coord_b"].pk),
        "scope": f"project:{two_orgs['uca'].pk}",
        "role": Role.VIEWER,
    })
    assert resp.status_code == 403
    assert not Membership.objects.filter(
        user=two_orgs["coord_b"], project=two_orgs["uca"]
    ).exists()


def test_approval_binds_user_to_granter_org(client, django_user_model, two_orgs):
    pending = django_user_model.objects.create_user("new@x.org", "pw", is_active=False)
    assert pending.organization_id is None
    client.force_login(two_orgs["coord_a"])
    resp = client.post(reverse("dashboards:team_grant"), {
        "user": str(pending.pk),
        "scope": f"project:{two_orgs['uca'].pk}",
        "role": Role.ENUMERATOR,
    })
    assert resp.status_code == 302
    pending.refresh_from_db()
    assert pending.is_active is True
    assert pending.organization_id == two_orgs["a"].id  # bound to A on approval


# --- tenancy fallback helpers ---


def test_invite_external_collaborator_to_one_project(client, two_orgs):
    """An owner shares one project with another org's user; isolation otherwise holds."""
    client.force_login(two_orgs["coord_a"])
    resp = client.post(reverse("dashboards:team_invite"), {
        "email": "b@x.org",  # coord_b belongs to Institution B
        "scope": f"project:{two_orgs['uca'].pk}",
        "role": Role.VIEWER,
    })
    assert resp.status_code == 302
    b = two_orgs["coord_b"]
    assert Membership.objects.filter(
        user=b, project=two_orgs["uca"], role=Role.VIEWER
    ).exists()
    # B's home institution is unchanged...
    b.refresh_from_db()
    assert b.organization_id == two_orgs["b"].id
    # ...and B now sees the shared A project, but not A's other data.
    visible = set(visible_projects(b).values_list("code", flat=True))
    assert visible == {"B-BIO", "A-SNS"}


def test_collaboration_only_on_project_not_region(client, two_orgs):
    client.force_login(two_orgs["coord_a"])
    resp = client.post(reverse("dashboards:team_invite"), {
        "email": "b@x.org",
        "scope": f"region:{two_orgs['ra'].pk}",  # not allowed
        "role": Role.VIEWER,
    })
    assert resp.status_code == 302  # redirected with an error message
    assert not Membership.objects.filter(
        user=two_orgs["coord_b"], region=two_orgs["ra"]
    ).exists()


def test_invite_unknown_email_does_nothing(client, two_orgs):
    client.force_login(two_orgs["coord_a"])
    before = Membership.objects.count()
    resp = client.post(reverse("dashboards:team_invite"), {
        "email": "nobody@x.org",
        "scope": f"project:{two_orgs['uca'].pk}",
        "role": Role.VIEWER,
    })
    assert resp.status_code == 302
    assert Membership.objects.count() == before


def test_invite_outside_authority_rejected(client, django_user_model, two_orgs):
    """A can't invite to B's project — A has no authority over it."""
    client.force_login(two_orgs["coord_a"])
    outsider = django_user_model.objects.create_user("out@x.org", "pw", is_active=True)
    resp = client.post(reverse("dashboards:team_invite"), {
        "email": "out@x.org",
        "scope": f"project:{two_orgs['ucb'].pk}",  # B's project
        "role": Role.VIEWER,
    })
    assert resp.status_code == 403
    assert not Membership.objects.filter(user=outsider).exists()


def test_default_organization_single_tenant():
    org = Organization.objects.create(code="solo", name="Solo Institution")
    assert default_organization() == org  # exactly one → it is the default


def test_resolve_organization_by_code_then_fallback():
    a = Organization.objects.create(code="default", name="Default")
    b = Organization.objects.create(code="named", name="Named")
    assert resolve_organization("named") == b
    # Unknown code falls back to the conventional default (two orgs exist).
    assert resolve_organization("missing") == a
    assert resolve_organization(None) == a
