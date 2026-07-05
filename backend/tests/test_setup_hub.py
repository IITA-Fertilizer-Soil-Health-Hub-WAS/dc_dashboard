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
    assert "Forms" in body and "Plot election" in body
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
