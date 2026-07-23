"""Project = workspace: active-project context, single-project landing, tabs."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.projects.models import Organization, Project
from apps.rbac.models import Membership, Role

pytestmark = pytest.mark.django_db


def _member(dj, org, *projects):
    u = dj.objects.create_user(f"u{id(projects)}@x.org", "pw", is_active=True, organization=org)
    for uc in projects:
        Membership.objects.create(user=u, project=uc, role=Role.VIEWER)
    return u


@pytest.fixture
def org():
    return Organization.objects.create(code="o", name="O")


def test_opening_a_project_sets_active_workspace(client, django_user_model, org):
    uc = Project.objects.create(code="PROJ-A", name="A", organization=org)
    u = _member(django_user_model, org, uc)
    client.force_login(u)
    resp = client.get(reverse("dashboards:project", args=["PROJ-A"]))
    assert resp.status_code == 200
    assert client.session["active_project"] == "PROJ-A"


def test_tab_deep_link(client, django_user_model, org):
    uc = Project.objects.create(code="PROJ-A", name="A", organization=org)
    u = _member(django_user_model, org, uc)
    client.force_login(u)
    resp = client.get(reverse("dashboards:project", args=["PROJ-A"]) + "?tab=review")
    assert resp.context["active_tab"] == "review"
    # An unknown tab falls back to summary.
    resp2 = client.get(reverse("dashboards:project", args=["PROJ-A"]) + "?tab=bogus")
    assert resp2.context["active_tab"] == "summary"


def test_single_project_user_lands_in_workspace(client, django_user_model, org):
    uc = Project.objects.create(code="ONLY", name="Only", organization=org)
    u = _member(django_user_model, org, uc)
    client.force_login(u)
    resp = client.get("/")
    assert resp.status_code == 302
    assert resp.url == reverse("dashboards:project", args=["ONLY"])


def test_multi_project_user_sees_picker(client, django_user_model, org):
    a = Project.objects.create(code="A", name="A", organization=org)
    b = Project.objects.create(code="B", name="B", organization=org)
    u = _member(django_user_model, org, a, b)
    client.force_login(u)
    resp = client.get("/")
    assert resp.status_code == 200  # the picker, no redirect


def test_sidebar_shows_four_numbered_lifecycle_phases(client, django_user_model, org):
    """The workspace rail groups every link under the four life-cycle phases
    (Set up → Collect → Review & approve → Monitor), each a numbered step, so
    the nav itself teaches the sequence."""
    uc = Project.objects.create(code="PROJ-A", name="A", organization=org)
    admin = django_user_model.objects.create_superuser("a@x.org", "pw")
    client.force_login(admin)
    body = client.get(reverse("dashboards:project", args=["PROJ-A"])).content.decode()
    # Exactly the four phase headers, all rendered as numbered steps.
    for label in ("Set up", "Collect", "Review &amp; approve", "Monitor"):
        assert f'class="lbl step"' in body and f">{label}</div>" in body
    assert body.count('class="lbl step"') == 4
    # The retired six-stage labels are gone.
    for gone in ("Field register", "Assign &amp; access", ">Finalize<"):
        assert gone not in body


def test_browsing_directory_clears_active_workspace(client, django_user_model, org):
    a = Project.objects.create(code="A", name="A", organization=org)
    b = Project.objects.create(code="B", name="B", organization=org)
    u = _member(django_user_model, org, a, b)
    client.force_login(u)
    client.get(reverse("dashboards:project", args=["A"]))
    assert client.session["active_project"] == "A"
    client.get(reverse("dashboards:projects"))  # opening the directory leaves the workspace
    assert "active_project" not in client.session
