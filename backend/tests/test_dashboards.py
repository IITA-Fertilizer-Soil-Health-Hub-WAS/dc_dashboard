"""Dashboard tests: RBAC-scoped views, tabs render, inline actions gated."""
from __future__ import annotations

from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse

from apps.config_admin.loader import import_config, load_yaml
from apps.ingestion.sync import sync_use_case
from apps.rbac.models import Role, UseCaseMembership
from apps.submissions.models import Submission, SubmissionValue
from apps.usecases.models import UseCase
from apps.validation.engine import run_for_use_case
from tests.test_ingestion import FakeOnaClient, _records

pytestmark = pytest.mark.django_db

SNS_PATH = Path(settings.USECASE_CONFIG_DIR) / "sns-rwanda.yaml"


@pytest.fixture
def setup(django_user_model):
    uc = import_config(load_yaml(SNS_PATH))
    sync_use_case(uc, client=FakeOnaClient(_records()))
    # Make one submission's ENID invalid so an Issue appears.
    s = Submission.objects.get(ona_uuid="uuid-aaa")
    SubmissionValue.objects.filter(submission=s, field_key="ENID").update(current_value="BADID")
    run_for_use_case(uc)

    other = UseCase.objects.create(code="KALRO", name="KALRO", is_active=True)
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True)
    viewer = django_user_model.objects.create_user("v@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=coord, use_case=uc, role=Role.TRIAL_COORDINATOR)
    UseCaseMembership.objects.create(user=viewer, use_case=uc, role=Role.VIEWER)
    return uc, other, coord, viewer, s


def test_index_lists_only_scoped_use_cases(client, setup):
    uc, other, coord, _, _ = setup
    client.force_login(coord)
    resp = client.get(reverse("dashboards:index"))
    assert resp.status_code == 200
    assert b"SNS-RWANDA" in resp.content
    assert b"KALRO" not in resp.content  # no membership


def test_cannot_open_unpermitted_use_case(client, setup):
    _, other, coord, _, _ = setup
    client.force_login(coord)
    resp = client.get(reverse("dashboards:usecase", args=[other.code]))
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
