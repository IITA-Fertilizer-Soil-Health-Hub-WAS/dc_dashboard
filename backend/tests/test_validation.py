"""Validation engine tests: rule firing, flag reconciliation, auto-FLAGGED."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from django.conf import settings

from apps.config_admin.loader import import_config, load_yaml
from apps.ingestion.sync import sync_project
from apps.review.models import ReviewState
from apps.submissions.models import Submission, SubmissionValue
from apps.validation.engine import run_for_project
from apps.validation.models import ValidationFlag
from apps.validation.status import event_status
from tests.test_ingestion import FakeOnaClient, _records

pytestmark = pytest.mark.django_db

SNS_PATH = Path(settings.USECASE_CONFIG_DIR) / "sns-rwanda.yaml"


@pytest.fixture
def project():
    uc = import_config(load_yaml(SNS_PATH))
    sync_project(uc, client=FakeOnaClient(_records()))
    return uc


def test_clean_data_no_id_flags(project):
    run_for_project(project)
    # Valid RSENRW/RSHHRW ids -> no REGEX_ID flags.
    assert not ValidationFlag.objects.filter(rule__code="enid_pattern").exists()
    assert not ValidationFlag.objects.filter(rule__code="hhid_pattern").exists()


def test_bad_enid_is_flagged_and_review_flagged(project):
    # Corrupt an ENID value so it fails ^RSENRW.
    s = Submission.objects.get(ona_uuid="uuid-aaa")
    SubmissionValue.objects.filter(submission=s, field_key="ENID").update(
        current_value="BADID001"
    )
    stats = run_for_project(project)

    flag = ValidationFlag.objects.get(submission=s, rule__code="enid_pattern")
    assert flag.message == "Check ENID"
    assert flag.severity == "ERROR"
    assert flag.status == ValidationFlag.Status.OPEN
    # ERROR flag auto-moved the review to FLAGGED.
    s.refresh_from_db()
    assert s.review.state == ReviewState.FLAGGED
    assert stats.flagged_submissions >= 1


def test_flag_auto_resolves_when_fixed(project):
    s = Submission.objects.get(ona_uuid="uuid-aaa")
    SubmissionValue.objects.filter(submission=s, field_key="ENID").update(current_value="BADID")
    run_for_project(project)
    assert ValidationFlag.objects.filter(
        submission=s, rule__code="enid_pattern", status="OPEN"
    ).exists()

    # Fix it and re-run: the prior flag is auto-resolved.
    SubmissionValue.objects.filter(submission=s, field_key="ENID").update(
        current_value="RSENRW000123"
    )
    run_for_project(project)
    flag = ValidationFlag.objects.get(submission=s, rule__code="enid_pattern")
    assert flag.status == ValidationFlag.Status.RESOLVED


def test_event_sequence_flagged(project):
    # Household has Event1 + Event2 already; delete Event1 to create a gap.
    Submission.objects.filter(project=project, event_key="Event1").delete()
    run_for_project(project)
    assert ValidationFlag.objects.filter(rule__code="event_sequence").exists()


def test_idempotent_no_duplicate_flags(project):
    s = Submission.objects.get(ona_uuid="uuid-aaa")
    SubmissionValue.objects.filter(submission=s, field_key="ENID").update(current_value="BADID")
    run_for_project(project)
    run_for_project(project)
    assert ValidationFlag.objects.filter(submission=s, rule__code="enid_pattern").count() == 1


def test_event_status_helper():
    anchor = date(2026, 1, 10)
    today = date(2026, 3, 1)
    # Submitted -> complete regardless of timing.
    assert event_status(
        event_date=date(2026, 1, 24), anchor_date=anchor, offset_days=14, grace_days=0, today=today
    ) == "complete"
    # Not submitted, past target -> overdue.
    assert event_status(
        event_date=None, anchor_date=anchor, offset_days=14, grace_days=0, today=today
    ) == "overdue"
    # Not submitted, within window -> due.
    assert event_status(
        event_date=None, anchor_date=anchor, offset_days=14, grace_days=0, today=date(2026, 1, 15)
    ) == "due"
    # Anchor unknown -> future.
    assert event_status(
        event_date=None, anchor_date=None, offset_days=14, grace_days=0, today=today
    ) == "future"
