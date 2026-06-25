"""Review workflow tests: state machine, role gating, audit trail, raw-vs-edited."""
from __future__ import annotations

from pathlib import Path

import pytest
from django.conf import settings

from apps.config_admin.loader import import_config, load_yaml
from apps.ingestion.sync import sync_use_case
from apps.rbac.models import Role, UseCaseMembership
from apps.review import services
from apps.review.models import Review, ReviewActionLog, ReviewState
from apps.review.state_machine import ReviewPermissionDenied, TransitionError
from apps.submissions.models import Submission, SubmissionValue
from tests.test_ingestion import FakeOnaClient, _records

pytestmark = pytest.mark.django_db

SNS_PATH = Path(settings.USECASE_CONFIG_DIR) / "sns-rwanda.yaml"


@pytest.fixture
def synced(django_user_model):
    uc = import_config(load_yaml(SNS_PATH))
    sync_use_case(uc, client=FakeOnaClient(_records()))
    submission = Submission.objects.get(ona_uuid="uuid-aaa")

    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True)
    qc = django_user_model.objects.create_user("q@x.org", "pw", is_active=True)
    viewer = django_user_model.objects.create_user("v@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=coord, use_case=uc, role=Role.TRIAL_COORDINATOR)
    UseCaseMembership.objects.create(user=qc, use_case=uc, role=Role.QUALITY_CHECK)
    UseCaseMembership.objects.create(user=viewer, use_case=uc, role=Role.VIEWER)
    return uc, submission, coord, qc, viewer


def test_review_created_on_ingest(synced):
    _, submission, *_ = synced
    assert Review.objects.filter(submission=submission).exists()
    assert submission.review.state == ReviewState.INGESTED


def test_coordinator_can_decline_and_audit_logged(synced):
    _, submission, coord, *_ = synced
    review = services.decline(coord, submission, note="bad GPS")
    assert review.state == ReviewState.DECLINED
    log = ReviewActionLog.objects.get(submission=submission, action="DECLINE")
    assert log.actor == coord
    assert log.from_state == ReviewState.INGESTED
    assert log.to_state == ReviewState.DECLINED
    assert log.note == "bad GPS"


def test_viewer_cannot_decline(synced):
    _, submission, _, _, viewer = synced
    with pytest.raises(ReviewPermissionDenied):
        services.decline(viewer, submission)
    # No state change, no audit entry written.
    assert submission.review.state == ReviewState.INGESTED
    assert not ReviewActionLog.objects.filter(submission=submission).exists()


def test_qc_cannot_decline_coordinator_can_not_approve(synced):
    _, submission, coord, qc, _ = synced
    with pytest.raises(ReviewPermissionDenied):
        services.qc_approve(coord, submission)
    with pytest.raises(ReviewPermissionDenied):
        services.decline(qc, submission)


def test_edit_value_updates_current_only_and_moves_to_edited(synced):
    _, submission, coord, *_ = synced
    review = services.edit_value(coord, submission, "Country", "Rwanda-fixed", note="typo")
    assert review.state == ReviewState.EDITED

    v = SubmissionValue.objects.get(submission=submission, field_key="Country")
    assert v.current_value == "Rwanda-fixed"
    assert v.is_edited is True
    assert v.edited_by == coord
    # raw_value untouched (immutable).
    assert v.raw_value == "Rwanda"

    log = ReviewActionLog.objects.get(submission=submission, action="EDIT_VALUE")
    assert log.field_key == "Country"
    assert log.old_value == "Rwanda"
    assert log.new_value == "Rwanda-fixed"


def test_full_happy_path_to_approved(synced):
    _, submission, coord, qc, _ = synced
    services.open_review(coord, submission)
    services.edit_value(coord, submission, "Country", "Rwanda-fixed")
    review = services.qc_approve(qc, submission, note="looks good")
    assert review.state == ReviewState.APPROVED
    assert review.qc_signed_by == qc
    assert review.qc_signed_at is not None
    # Audit trail captured every step in order.
    actions = list(
        ReviewActionLog.objects.filter(submission=submission).values_list("action", flat=True)
    )
    assert actions == ["OPEN_REVIEW", "EDIT_VALUE", "QC_APPROVE"]


def test_illegal_transition_rejected(synced):
    _, submission, coord, qc, _ = synced
    services.decline(coord, submission)  # -> DECLINED
    # Cannot QC-approve a declined submission without reopening.
    with pytest.raises(TransitionError):
        services.qc_approve(qc, submission)
    # Reopen path works.
    services.reopen(coord, submission)
    assert submission.review.state == ReviewState.IN_REVIEW


def test_cross_use_case_isolation(synced, django_user_model):
    uc, submission, *_ = synced
    from apps.usecases.models import UseCase

    other = UseCase.objects.create(code="KALRO", name="KALRO")
    intruder = django_user_model.objects.create_user("i@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=intruder, use_case=other, role=Role.TRIAL_COORDINATOR)
    # Coordinator of KALRO cannot act on an SNS-RWANDA submission.
    with pytest.raises(ReviewPermissionDenied):
        services.decline(intruder, submission)
