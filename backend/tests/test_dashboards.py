"""Dashboard tests: RBAC-scoped views, tabs render, inline actions gated."""
from __future__ import annotations

from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse

from apps.config_admin.loader import import_config, load_yaml
from apps.ingestion.sync import sync_project
from apps.projects.models import Project
from apps.rbac.models import Membership, Role
from apps.submissions.models import Submission, SubmissionValue
from apps.validation.engine import run_for_project
from tests.test_ingestion import FakeOnaClient, _records

pytestmark = pytest.mark.django_db

SNS_PATH = Path(settings.PROJECT_CONFIG_DIR) / "sns-rwanda.yaml"


@pytest.fixture
def setup(django_user_model):
    uc = import_config(load_yaml(SNS_PATH))
    sync_project(uc, client=FakeOnaClient(_records()))
    # Make one submission's ENID invalid so an Issue appears.
    s = Submission.objects.get(ona_uuid="uuid-aaa")
    SubmissionValue.objects.filter(submission=s, field_key="ENID").update(current_value="BADID")
    run_for_project(uc)

    other = Project.objects.create(code="KALRO", name="KALRO", is_active=True)
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True)
    viewer = django_user_model.objects.create_user("v@x.org", "pw", is_active=True)
    Membership.objects.create(user=coord, project=uc, role=Role.TRIAL_COORDINATOR)
    Membership.objects.create(user=viewer, project=uc, role=Role.VIEWER)
    return uc, other, coord, viewer, s


def test_index_lands_single_project_user_in_their_project(client, setup):
    uc, other, coord, _, _ = setup
    client.force_login(coord)
    resp = client.get(reverse("dashboards:index"))
    # Project = workspace: a user with exactly one project (SNS-RWANDA, not the
    # unpermitted KALRO) is taken straight into it.
    assert resp.status_code == 302
    assert resp.url == reverse("dashboards:project", args=["SNS-RWANDA"])


def test_cannot_open_unpermitted_project(client, setup):
    _, other, coord, _, _ = setup
    client.force_login(coord)
    resp = client.get(reverse("dashboards:project", args=[other.code]))
    assert resp.status_code == 404


def test_tabs_render(client, setup):
    uc, _, coord, _, _ = setup
    client.force_login(coord)
    for tab in ["tab_summary", "tab_enumerators", "tab_issues", "tab_data"]:
        resp = client.get(reverse(f"dashboards:{tab}", args=[uc.code]))
        assert resp.status_code == 200


def test_issues_shows_action_buttons_for_coordinator(client, setup):
    uc, _, coord, _, _ = setup
    client.force_login(coord)
    resp = client.get(reverse("dashboards:tab_issues", args=[uc.code]))
    assert b"Decline" in resp.content
    assert b"Check ENID" in resp.content


def test_issues_hides_actions_for_viewer(client, setup):
    uc, _, _, viewer, _ = setup
    client.force_login(viewer)
    resp = client.get(reverse("dashboards:tab_issues", args=[uc.code]))
    # Match button text precisely (">Decline<"), not the "Declined" state-filter option.
    assert b">Decline</button>" not in resp.content
    assert b">QC approve</button>" not in resp.content


def test_inline_decline_action(client, setup):
    uc, _, coord, _, s = setup
    client.force_login(coord)
    resp = client.post(
        reverse("dashboards:submission_action", args=[uc.code, s.id]),
        data={"action": "DECLINE", "note": "bad id"},
    )
    assert resp.status_code == 200
    s.refresh_from_db()
    assert s.review.state == "DECLINED"


def test_inline_action_denied_for_viewer(client, setup):
    uc, _, _, viewer, s = setup
    client.force_login(viewer)
    resp = client.post(
        reverse("dashboards:submission_action", args=[uc.code, s.id]),
        data={"action": "DECLINE"},
    )
    # Renders the panel with an error, no state change.
    assert resp.status_code == 200
    assert b"cannot DECLINE" in resp.content
    s.refresh_from_db()
    assert s.review.state != "DECLINED"
