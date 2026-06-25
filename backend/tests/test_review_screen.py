"""The full-page submission review/edit screen in the dashboards."""
from __future__ import annotations

import pytest

from apps.rbac.models import Role, UseCaseMembership
from apps.review.models import ReviewState
from apps.submissions.models import Submission, SubmissionValue
from apps.usecases.models import FormDefinition, UseCase

pytestmark = pytest.mark.django_db


@pytest.fixture
def uc():
    return UseCase.objects.create(code="UC", name="UC")


@pytest.fixture
def submission(uc):
    form = FormDefinition.objects.create(use_case=uc, ona_form_id=1,
                                         role=FormDefinition.Role.VALIDATION)
    sub = Submission.objects.create(use_case=uc, form=form, ona_uuid="u1", content_hash="h")
    SubmissionValue.objects.create(submission=sub, field_key="ENID",
                                   raw_value="EN1", current_value="EN1")
    return sub


@pytest.fixture
def coordinator(django_user_model, uc):
    user = django_user_model.objects.create_user("c@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=user, use_case=uc, role=Role.TRIAL_COORDINATOR)
    return user


@pytest.fixture
def viewer(django_user_model, uc):
    user = django_user_model.objects.create_user("v@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=user, use_case=uc, role=Role.VIEWER)
    return user


def _url(sub):
    return f"/usecase/{sub.use_case.code}/submission/{sub.pk}/review/"


def test_review_page_renders(client, coordinator, submission):
    client.force_login(coordinator)
    resp = client.get(_url(submission))
    assert resp.status_code == 200
    assert b"Field values" in resp.content
    assert b"Save edits" in resp.content  # coordinator can edit


def test_viewer_cannot_edit(client, viewer, submission):
    client.force_login(viewer)
    resp = client.get(_url(submission))
    assert resp.status_code == 200
    assert b"Save edits" not in resp.content  # read-only for viewers


def test_save_edits_updates_authoritative_value(client, coordinator, submission):
    client.force_login(coordinator)
    resp = client.post(_url(submission), {"action": "save_edits", "val-ENID": "EN1-FIXED"})
    assert resp.status_code == 200
    value = submission.values.get(field_key="ENID")
    assert value.current_value == "EN1-FIXED"
    assert value.raw_value == "EN1"  # raw preserved
    assert value.is_edited is True
    submission.refresh_from_db()
    assert submission.writeback_status == Submission.WriteBackStatus.PENDING


def test_workflow_action_from_screen(client, coordinator, submission):
    client.force_login(coordinator)
    resp = client.post(_url(submission), {"action": "DECLINE", "note": "bad data"})
    assert resp.status_code == 200
    submission.refresh_from_db()
    assert submission.review.state == ReviewState.DECLINED


def test_viewer_save_edits_denied(client, viewer, submission):
    client.force_login(viewer)
    resp = client.post(_url(submission), {"action": "save_edits", "val-ENID": "HACK"})
    assert resp.status_code == 200
    assert submission.values.get(field_key="ENID").current_value == "EN1"  # unchanged
