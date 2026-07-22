"""Read API: RBAC-scoped, paginated, token- or session-authenticated."""
from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.projects.models import FormDefinition, Organization, Project
from apps.rbac.models import Membership, Role
from apps.submissions.models import Submission

pytestmark = pytest.mark.django_db


@pytest.fixture
def data(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    vis = Project.objects.create(code="VIS", name="Visible", organization=org)
    Project.objects.create(code="HID", name="Hidden")  # user can't see this one
    f = FormDefinition.objects.create(project=vis, ona_form_id=1,
                                      role=FormDefinition.Role.VALIDATION)
    Submission.objects.create(project=vis, form=f, ona_uuid="u1", content_hash="h1",
                              event_key="Event1")
    user = django_user_model.objects.create_user("u@x.org", "pw", is_active=True,
                                                  organization=org)
    Membership.objects.create(user=user, project=vis, role=Role.TRIAL_COORDINATOR)
    return {"user": user, "vis": vis}


def test_projects_endpoint_is_rbac_scoped(data):
    c = APIClient(); c.force_authenticate(data["user"])
    resp = c.get("/api/v1/projects/")
    assert resp.status_code == 200
    codes = {row["code"] for row in resp.json()}
    assert "VIS" in codes and "HID" not in codes


def test_submissions_paginated_and_scoped(data):
    c = APIClient(); c.force_authenticate(data["user"])
    resp = c.get("/api/v1/projects/VIS/submissions/?values=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1 and body["results"][0]["ona_uuid"] == "u1"
    # A project the caller can't see is a 404, not a leak.
    assert c.get("/api/v1/projects/HID/submissions/").status_code == 404


def test_token_authentication_works(data):
    from rest_framework.authtoken.models import Token
    token = Token.objects.create(user=data["user"])
    resp = APIClient().get("/api/v1/projects/", HTTP_AUTHORIZATION=f"Token {token.key}")
    assert resp.status_code == 200


def test_unauthenticated_is_denied(data):
    assert APIClient().get("/api/v1/projects/").status_code in (401, 403)


def test_data_products_page_and_token_generation(client, data):
    client.force_login(data["user"])
    assert client.get(reverse("console:data_products")).status_code == 200
    client.post(reverse("console:data_products"))  # generate
    from rest_framework.authtoken.models import Token
    assert Token.objects.filter(user=data["user"]).exists()
