"""The one-page project Set up hub: grouped config cards with live counts."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.projects.models import Crop, FormDefinition, Organization, Project
from apps.rbac.models import Membership, Role

pytestmark = pytest.mark.django_db


@pytest.fixture
def proj(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    p = Project.objects.create(code="SL", name="Sierra Leone", organization=org)
    FormDefinition.objects.create(project=p, ona_form_id=1, title="A",
                                  role=FormDefinition.Role.VALIDATION)
    Crop.objects.create(project=p, name="Rice")
    admin = django_user_model.objects.create_superuser("a@x.org", "pw")
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True,
                                                   organization=org)
    Membership.objects.create(user=coord, project=p, role=Role.TRIAL_COORDINATOR)
    return {"p": p, "admin": admin, "coord": coord, "org": org}


def test_setup_hub_renders_with_counts(client, proj):
    client.force_login(proj["admin"])
    session = client.session
    session["active_project"] = proj["p"].code
    session.save()
    resp = client.get(reverse("console:setup") + f"?project={proj['p'].code}")
    assert resp.status_code == 200
    body = resp.content.decode()
    # Grouped sections and the live counts are present, no comment leaks.
    assert "Instrument" in body and "Quality rules" in body
    assert "Forms" in body and "Choose plots" in body
    assert "areas configured" in body
    for leak in ("{#", "{% comment", "{% widthratio"):
        assert leak not in body


def test_setup_hub_scoped_to_visible_projects(client, proj, django_user_model):
    """A coordinator asking for a project they can't see falls back to their own,
    never another org's project."""
    other = Project.objects.create(code="OTHER", name="Other")
    client.force_login(proj["coord"])
    resp = client.get(reverse("console:setup") + f"?project={other.code}")
    assert resp.status_code == 200
    # Falls back to the coordinator's own project, not OTHER.
    assert "Sierra Leone" in resp.content.decode()
    assert "Other" not in resp.content.decode()


def test_setup_hub_denied_for_plain_member(client, proj, django_user_model):
    member = django_user_model.objects.create_user("m@x.org", "pw", is_active=True)
    Membership.objects.create(user=member, project=proj["p"], role=Role.VIEWER)
    client.force_login(member)
    resp = client.get(reverse("console:setup") + f"?project={proj['p'].code}")
    assert resp.status_code == 403


def test_inline_quick_add_creates_and_returns_card(client, proj):
    """POST to a card's quick-add creates the row (auto-scoped to the project)
    and returns the refreshed card with the new count."""
    from apps.review.models import RejectionReason

    client.force_login(proj["admin"])
    session = client.session
    session["active_project"] = proj["p"].code
    session.save()
    url = reverse("console:setup_add", args=["rejection-reasons"]) + f"?project={proj['p'].code}"
    resp = client.post(url, {"code": "DUP", "label": "Duplicate record"})
    assert resp.status_code == 200
    rr = RejectionReason.objects.get(project=proj["p"], code="DUP")
    assert rr.label == "Duplicate record" and rr.is_active and rr.order >= 1  # defaults applied
    body = resp.content.decode()
    assert 'class="scard"' in body and "Duplicate record" in body


def test_inline_quick_add_invalid_reopens_with_error(client, proj):
    client.force_login(proj["admin"])
    session = client.session
    session["active_project"] = proj["p"].code
    session.save()
    url = reverse("console:setup_add", args=["crops"]) + f"?project={proj['p'].code}"
    resp = client.post(url, {"name": ""})  # name required
    assert resp.status_code == 200
    assert "<details class=\"qadd\" open>" in resp.content.decode()


def test_quick_add_denied_for_wrong_scope(client, proj, django_user_model):
    """A trial coordinator (not a geo manager) cannot quick-add crops."""
    coord = proj["coord"]
    client.force_login(coord)
    session = client.session
    session["active_project"] = proj["p"].code
    session.save()
    url = reverse("console:setup_add", args=["crops"]) + f"?project={proj['p'].code}"
    assert client.post(url, {"name": "Maize"}).status_code == 403


def test_admin_setup_hub(client, proj, django_user_model):
    client.force_login(proj["admin"])
    resp = client.get(reverse("console:admin_setup"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Institutions" in body and "Regions" in body and "Countries" in body
    # Non-staff cannot reach the tenancy hub.
    client.force_login(proj["coord"])
    assert client.get(reverse("console:admin_setup")).status_code == 403
