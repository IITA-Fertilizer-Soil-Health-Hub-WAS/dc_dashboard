"""HTTP-level tests for the review action API (DRF)."""
from __future__ import annotations

from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse

from apps.config_admin.loader import import_config, load_yaml
from apps.ingestion.sync import sync_project
from apps.rbac.models import Membership, Role
from apps.submissions.models import Submission
from tests.test_ingestion import FakeOnaClient, _records

pytestmark = pytest.mark.django_db

SNS_PATH = Path(settings.PROJECT_CONFIG_DIR) / "sns-rwanda.yaml"


@pytest.fixture
def setup(django_user_model):
    uc = import_config(load_yaml(SNS_PATH))
    sync_project(uc, client=FakeOnaClient(_records()))
    submission = Submission.objects.get(ona_uuid="uuid-aaa")
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True)
    viewer = django_user_model.objects.create_user("v@x.org", "pw", is_active=True)
    Membership.objects.create(user=coord, project=uc, role=Role.TRIAL_COORDINATOR)
    Membership.objects.create(user=viewer, project=uc, role=Role.VIEWER)
    return submission, coord, viewer


def _url(submission):
    return reverse("api:review-action", args=[submission.id])


def test_coordinator_decline_via_api(client, setup):
    submission, coord, _ = setup
    client.force_login(coord)
    resp = client.post(
        _url(submission), data={"action": "DECLINE", "note": "bad"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "DECLINED"


def test_viewer_decline_forbidden_via_api(client, setup):
    submission, _, viewer = setup
    client.force_login(viewer)
    resp = client.post(
        _url(submission), data={"action": "DECLINE"}, content_type="application/json"
    )
    assert resp.status_code == 403


def test_edit_value_via_api(client, setup):
    submission, coord, _ = setup
    client.force_login(coord)
    resp = client.post(
        _url(submission),
        data={"action": "EDIT_VALUE", "field_key": "Country", "new_value": "Rwanda-fixed"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "EDITED"


def test_anonymous_denied(client, setup):
    submission, _, _ = setup
    resp = client.post(
        _url(submission), data={"action": "DECLINE"}, content_type="application/json"
    )
    assert resp.status_code in (401, 403)
