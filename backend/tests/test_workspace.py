"""Project = workspace: active-project context, single-project landing, tabs."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.rbac.models import Role, UseCaseMembership
from apps.usecases.models import Organization, UseCase

pytestmark = pytest.mark.django_db


def _member(dj, org, *use_cases):
    u = dj.objects.create_user(f"u{id(use_cases)}@x.org", "pw", is_active=True, organization=org)
    for uc in use_cases:
        UseCaseMembership.objects.create(user=u, use_case=uc, role=Role.VIEWER)
    return u


@pytest.fixture
def org():
    return Organization.objects.create(code="o", name="O")


def test_opening_a_project_sets_active_workspace(client, django_user_model, org):
    uc = UseCase.objects.create(code="PROJ-A", name="A", organization=org)
    u = _member(django_user_model, org, uc)
    client.force_login(u)
    resp = client.get(reverse("dashboards:usecase", args=["PROJ-A"]))
    assert resp.status_code == 200
    assert client.session["active_project"] == "PROJ-A"


def test_tab_deep_link(client, django_user_model, org):
    uc = UseCase.objects.create(code="PROJ-A", name="A", organization=org)
    u = _member(django_user_model, org, uc)
    client.force_login(u)
    resp = client.get(reverse("dashboards:usecase", args=["PROJ-A"]) + "?tab=review")
    assert resp.context["active_tab"] == "review"
    # An unknown tab falls back to summary.
    resp2 = client.get(reverse("dashboards:usecase", args=["PROJ-A"]) + "?tab=bogus")
    assert resp2.context["active_tab"] == "summary"


def test_single_project_user_lands_in_workspace(client, django_user_model, org):
    uc = UseCase.objects.create(code="ONLY", name="Only", organization=org)
    u = _member(django_user_model, org, uc)
    client.force_login(u)
    resp = client.get("/")
    assert resp.status_code == 302
    assert resp.url == reverse("dashboards:usecase", args=["ONLY"])


def test_multi_project_user_sees_picker(client, django_user_model, org):
    a = UseCase.objects.create(code="A", name="A", organization=org)
    b = UseCase.objects.create(code="B", name="B", organization=org)
    u = _member(django_user_model, org, a, b)
    client.force_login(u)
    resp = client.get("/")
    assert resp.status_code == 200  # the picker, no redirect


def test_browsing_directory_clears_active_workspace(client, django_user_model, org):
    a = UseCase.objects.create(code="A", name="A", organization=org)
    b = UseCase.objects.create(code="B", name="B", organization=org)
    u = _member(django_user_model, org, a, b)
    client.force_login(u)
    client.get(reverse("dashboards:usecase", args=["A"]))
    assert client.session["active_project"] == "A"
    client.get(reverse("dashboards:projects"))  # opening the directory leaves the workspace
    assert "active_project" not in client.session
