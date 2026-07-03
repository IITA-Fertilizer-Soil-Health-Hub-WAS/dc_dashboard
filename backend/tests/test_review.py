"""Review workflow tests: state machine, role gating, audit trail, raw-vs-edited."""
from __future__ import annotations

from pathlib import Path

import pytest
from django.conf import settings

from apps.config_admin.loader import import_config, load_yaml
from apps.ingestion.sync import sync_project
from apps.rbac.models import Role, UseCaseMembership
from apps.review import services
from apps.review.models import Review, ReviewActionLog, ReviewState
from apps.review.state_machine import ReviewPermissionDenied, TransitionError
from apps.submissions.models import Submission, SubmissionValue
from tests.test_ingestion import FakeOnaClient, _records

pytestmark = pytest.mark.django_db

SNS_PATH = Path(settings.PROJECT_CONFIG_DIR) / "sns-rwanda.yaml"


@pytest.fixture
def synced(django_user_model):
    uc = import_config(load_yaml(SNS_PATH))
    sync_project(uc, client=FakeOnaClient(_records()))
    submission = Submission.objects.get(ona_uuid="uuid-aaa")

    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True)
    qc = django_user_model.objects.create_user("q@x.org", "pw", is_active=True)
    viewer = django_user_model.objects.create_user("v@x.org", "pw", is_active=True)
    regional = django_user_model.objects.create_user("r@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=coord, project=uc, role=Role.TRIAL_COORDINATOR)
    UseCaseMembership.objects.create(user=qc, project=uc, role=Role.COUNTRY_COORDINATOR)
    UseCaseMembership.objects.create(user=viewer, project=uc, role=Role.VIEWER)
    UseCaseMembership.objects.create(user=regional, project=uc, role=Role.REGIONAL_COORDINATOR)
    # coord/qc = Gate 1 (endorse); regional = Gate 2 (final validation).
    return uc, submission, coord, qc, viewer, regional


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
    _, submission, _, _, viewer, _ = synced
    with pytest.raises(ReviewPermissionDenied):
        services.decline(viewer, submission)
    # No state change, no audit entry written.
    assert submission.review.state == ReviewState.INGESTED
    assert not ReviewActionLog.objects.filter(submission=submission).exists()


def test_two_gate_review(synced):
    """Gate 1 (Trial/Country) endorses; only Gate 2 (Regional) gives final validation."""
    _, submission, coord, qc, _, regional = synced

    # Gate 1: a Trial Coordinator endorses -> QC_PENDING.
    services.open_review(coord, submission)
    review = services.endorse(coord, submission, note="looks good, level 1")
    assert review.state == ReviewState.QC_PENDING
    assert review.endorsed_by == coord

    # A Gate-1 coordinator cannot give final validation.
    with pytest.raises(ReviewPermissionDenied):
        services.qc_approve(qc, submission)

    # Gate 2: the Regional Coordinator validates -> APPROVED.
    review = services.qc_approve(regional, submission, note="final ok")
    assert review.state == ReviewState.APPROVED
    assert review.qc_signed_by == regional


def test_regional_cannot_endorse_at_gate1(synced):
    """The final validator is not a Gate-1 endorser."""
    _, submission, _, _, _, regional = synced
    with pytest.raises(ReviewPermissionDenied):
        services.endorse(regional, submission)


def test_final_validation_requires_endorsement_first(synced):
    """A Regional Coordinator cannot validate a submission that skipped Gate 1."""
    _, submission, _, _, _, regional = synced
    with pytest.raises(TransitionError):
        services.qc_approve(regional, submission)  # still INGESTED, not QC_PENDING


def test_country_coordinator_fallback_validates_when_no_regional(django_user_model):
    """With no Regional on the use case, a second Country Coordinator validates."""
    from apps.projects.models import FormDefinition, Project

    uc = Project.objects.create(code="NOREG", name="No Regional")
    form = FormDefinition.objects.create(
        project=uc, ona_form_id=9, role=FormDefinition.Role.VALIDATION
    )
    sub = Submission.objects.create(project=uc, form=form, ona_uuid="nr", content_hash="h")
    a = django_user_model.objects.create_user("a@x.org", "pw", is_active=True)
    b = django_user_model.objects.create_user("b@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=a, project=uc, role=Role.COUNTRY_COORDINATOR)
    UseCaseMembership.objects.create(user=b, project=uc, role=Role.COUNTRY_COORDINATOR)

    services.endorse(a, sub)  # Gate 1
    review = services.qc_approve(b, sub)  # Gate 2 fallback (a different person)
    assert review.state == ReviewState.APPROVED
    assert review.qc_signed_by == b


def test_same_person_cannot_endorse_and_validate(synced, django_user_model):
    """Two-person rule: holding both roles still can't self-approve both gates."""
    uc, submission, *_ = synced
    both = django_user_model.objects.create_user("both@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=both, project=uc, role=Role.COUNTRY_COORDINATOR)
    UseCaseMembership.objects.create(user=both, project=uc, role=Role.REGIONAL_COORDINATOR)
    services.endorse(both, submission)
    with pytest.raises(ReviewPermissionDenied):
        services.qc_approve(both, submission)


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
    _, submission, coord, _, _, regional = synced
    services.open_review(coord, submission)
    services.edit_value(coord, submission, "Country", "Rwanda-fixed")
    services.endorse(coord, submission)  # Gate 1
    review = services.qc_approve(regional, submission, note="looks good")  # Gate 2
    assert review.state == ReviewState.APPROVED
    assert review.endorsed_by == coord
    assert review.qc_signed_by == regional
    assert review.qc_signed_at is not None
    # Audit trail captured every step in order.
    actions = list(
        ReviewActionLog.objects.filter(submission=submission).values_list("action", flat=True)
    )
    assert actions == ["OPEN_REVIEW", "EDIT_VALUE", "ENDORSE", "QC_APPROVE"]


def test_illegal_transition_rejected(synced):
    _, submission, coord, _, _, regional = synced
    services.decline(coord, submission)  # -> DECLINED
    # Cannot validate a declined submission without reopening.
    with pytest.raises(TransitionError):
        services.qc_approve(regional, submission)
    # Reopen path works.
    services.reopen(coord, submission)
    assert submission.review.state == ReviewState.IN_REVIEW


def test_cross_project_isolation(synced, django_user_model):
    uc, submission, *_ = synced
    from apps.projects.models import Project

    other = Project.objects.create(code="KALRO", name="KALRO")
    intruder = django_user_model.objects.create_user("i@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=intruder, project=other, role=Role.TRIAL_COORDINATOR)
    # Coordinator of KALRO cannot act on an SNS-RWANDA submission.
    with pytest.raises(ReviewPermissionDenied):
        services.decline(intruder, submission)
