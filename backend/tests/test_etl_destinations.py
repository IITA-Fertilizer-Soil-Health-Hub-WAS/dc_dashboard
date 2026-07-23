"""Outbound ETL: push cleaned data to destinations (incremental) + the
incremental read-API cursor for pull-based tools."""
from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.ingestion.destinations import push_destination
from apps.ingestion.models import Destination
from apps.projects.models import FormDefinition, Organization, Project
from apps.rbac.models import Membership, Role
from apps.review.models import Review, ReviewState
from apps.submissions.models import Submission, SubmissionValue

pytestmark = pytest.mark.django_db


class FakeResp:
    status_code = 200

    def raise_for_status(self):
        pass


@pytest.fixture
def proj(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    p = Project.objects.create(code="P", name="P", organization=org)
    FormDefinition.objects.create(project=p, ona_form_id=1, role=FormDefinition.Role.VALIDATION)
    admin = django_user_model.objects.create_superuser("a@x.org", "pw")
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True,
                                                  organization=org)
    Membership.objects.create(user=coord, project=p, role=Role.TRIAL_COORDINATOR)
    return {"p": p, "admin": admin, "coord": coord}


def _sub(project, uuid, values, approved=False):
    s = Submission.objects.create(project=project, form=project.forms.first(),
                                  ona_uuid=uuid, content_hash=uuid)
    for k, v in values.items():
        SubmissionValue.objects.create(submission=s, field_key=k, raw_value=str(v),
                                       current_value=str(v))
    if approved:
        Review.objects.update_or_create(submission=s,
                                        defaults={"state": ReviewState.APPROVED})
    return s


def test_push_is_incremental_and_recorded(proj, monkeypatch):
    p = proj["p"]
    _sub(p, "a", {"ph": "6.5"})
    _sub(p, "b", {"ph": "7.0"})
    sent = []
    monkeypatch.setattr("httpx.post",
                        lambda url, json=None, headers=None, timeout=None: sent.append(json) or FakeResp())
    dest = Destination.objects.create(project=p, name="wh", url="https://x/y",
                                      only_approved=False, kind="WEBHOOK")

    res = push_destination(dest)
    assert res["sent"] == 2 and dest.last_status == "OK" and dest.cursor is not None
    assert sent[0]["count"] == 2 and sent[0]["submissions"][0]["values"]  # rows + values

    # Second push has nothing new until data changes.
    assert push_destination(dest)["sent"] == 0
    _sub(p, "c", {"ph": "6.8"})
    assert push_destination(dest)["sent"] == 1  # only the new row


def test_push_only_approved_filter(proj, monkeypatch):
    p = proj["p"]
    _sub(p, "draft", {"ph": "6.5"}, approved=False)
    _sub(p, "ok", {"ph": "7.0"}, approved=True)
    monkeypatch.setattr("httpx.post",
                        lambda url, json=None, headers=None, timeout=None: FakeResp())
    dest = Destination.objects.create(project=p, name="wh", url="https://x/y",
                                      only_approved=True, kind="WEBHOOK")
    assert push_destination(dest)["sent"] == 1  # only the approved one


def test_push_records_error(proj, monkeypatch):
    p = proj["p"]
    _sub(p, "a", {"ph": "6.5"})

    def boom(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("httpx.post", boom)
    dest = Destination.objects.create(project=p, name="wh", url="https://x/y",
                                      only_approved=False, kind="WEBHOOK")
    res = push_destination(dest)
    assert res["status"] == "ERROR"
    dest.refresh_from_db()
    assert dest.last_status == "ERROR" and dest.cursor is None  # not advanced on failure


def test_destinations_view_create_and_list(client, proj):
    client.force_login(proj["admin"])
    s = client.session; s["active_project"] = proj["p"].code; s.save()
    client.post(reverse("console:destinations") + f"?project={proj['p'].code}",
                {"project": proj["p"].code, "name": "Warehouse", "url": "https://etl/x",
                 "only_approved": "on"})
    assert Destination.objects.filter(project=proj["p"], name="Warehouse").exists()
    body = client.get(reverse("console:destinations") + f"?project={proj['p'].code}").content.decode()
    assert "Warehouse" in body


def test_read_api_incremental_cursor(proj):
    p = proj["p"]
    old = _sub(p, "old", {"ph": "6.5"})
    new = _sub(p, "new", {"ph": "7.0"})
    c = APIClient(); c.force_authenticate(proj["admin"])
    cursor = old.updated_at.isoformat()
    resp = c.get(f"/api/v1/projects/{p.code}/submissions/",
                 {"updated_since": cursor})
    uuids = [r["ona_uuid"] for r in resp.json()["results"]]
    assert "new" in uuids and "old" not in uuids
