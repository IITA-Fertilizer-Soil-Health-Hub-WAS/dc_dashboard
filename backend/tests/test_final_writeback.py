"""Final-data gate (approved-only) + write-back of reviewer edits to source."""
from __future__ import annotations

import pytest

from apps.dashboards.final import approved_submissions, final_rows
from apps.ingestion import writeback
from apps.ingestion.backends.base import CollectionBackend, WriteResult
from apps.review import services
from apps.submissions.models import Submission, SubmissionValue
from apps.usecases.models import FormDefinition, UseCase

pytestmark = pytest.mark.django_db


@pytest.fixture
def coordinator(django_user_model):
    return django_user_model.objects.create_superuser("c@x.org", "pw")


@pytest.fixture
def submission():
    uc = UseCase.objects.create(code="UC", name="UC")
    form = FormDefinition.objects.create(use_case=uc, ona_form_id=1,
                                         role=FormDefinition.Role.VALIDATION)
    sub = Submission.objects.create(use_case=uc, form=form, ona_uuid="u1", content_hash="h")
    SubmissionValue.objects.create(submission=sub, field_key="ENID",
                                   raw_value="EN1", current_value="EN1")
    return sub


# ---- Final data gate ----
def test_only_approved_in_final_dataset(submission, coordinator):
    uc = submission.use_case
    assert approved_submissions(uc).count() == 0  # not yet approved
    services.qc_approve(coordinator, submission)
    assert approved_submissions(uc).count() == 1


def test_final_rows_use_authoritative_values(submission, coordinator):
    # Edit a value, then approve — final data must reflect the edited value.
    services.edit_value(coordinator, submission, field_key="ENID", new_value="EN1-FIXED")
    services.qc_approve(coordinator, submission)
    _, keys, rows = final_rows(submission.use_case)
    assert rows[0]["values"]["ENID"] == "EN1-FIXED"
    assert rows[0]["edited"] == 1


def test_export_final_csv(client, coordinator, submission):
    services.qc_approve(coordinator, submission)
    client.force_login(coordinator)
    resp = client.get(f"/usecase/{submission.use_case.code}/final.csv")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "text/csv"
    assert b"ona_uuid" in resp.content and b"u1" in resp.content


# ---- Write-back ----
def test_edit_marks_submission_pending(submission, coordinator):
    services.edit_value(coordinator, submission, field_key="ENID", new_value="EN1-FIXED")
    submission.refresh_from_db()
    assert submission.writeback_status == Submission.WriteBackStatus.PENDING


def test_capable_backend_pending_when_globally_disabled(submission, coordinator, settings, monkeypatch):
    # Backend *can* write back, but it's globally disabled -> queued (PENDING).
    settings.WRITEBACK_ENABLED = False
    services.edit_value(coordinator, submission, field_key="ENID", new_value="X")

    class WritableBackend(CollectionBackend):
        supports_writeback = True

        def push_edit(self, submission, changes):
            return WriteResult(ok=True)

    monkeypatch.setattr(writeback, "get_backend_for", lambda uc: WritableBackend())
    writeback.push_submission(submission)
    submission.refresh_from_db()
    assert submission.writeback_status == Submission.WriteBackStatus.PENDING


def test_writeback_sends_when_enabled(submission, coordinator, settings, monkeypatch):
    settings.WRITEBACK_ENABLED = True
    services.edit_value(coordinator, submission, field_key="ENID", new_value="X")

    captured = {}

    class WritableBackend(CollectionBackend):
        supports_writeback = True
        label = "Writable"

        def push_edit(self, submission, changes):
            captured["changes"] = changes
            return WriteResult(ok=True, message="ok", remote_id="r1")

    monkeypatch.setattr(writeback, "get_backend_for", lambda uc: WritableBackend())
    writeback.push_submission(submission)
    submission.refresh_from_db()
    assert submission.writeback_status == Submission.WriteBackStatus.SENT
    assert captured["changes"] == {"ENID": "X"}  # only edited fields pushed


def test_writeback_unsupported_backend(submission, coordinator, settings, monkeypatch):
    settings.WRITEBACK_ENABLED = True
    services.edit_value(coordinator, submission, field_key="ENID", new_value="X")
    monkeypatch.setattr(writeback, "get_backend_for", lambda uc: CollectionBackend())
    writeback.push_submission(submission)
    submission.refresh_from_db()
    assert submission.writeback_status == Submission.WriteBackStatus.UNSUPPORTED


def test_approve_triggers_writeback(submission, coordinator, settings, monkeypatch):
    # Eager Celery in tests: approving runs the write-back task inline.
    settings.WRITEBACK_ENABLED = True
    settings.CELERY_TASK_ALWAYS_EAGER = True
    services.edit_value(coordinator, submission, field_key="ENID", new_value="X")

    class WritableBackend(CollectionBackend):
        supports_writeback = True

        def push_edit(self, submission, changes):
            return WriteResult(ok=True, message="ok")

    monkeypatch.setattr(writeback, "get_backend_for", lambda uc: WritableBackend())
    services.qc_approve(coordinator, submission)
    submission.refresh_from_db()
    assert submission.writeback_status == Submission.WriteBackStatus.SENT
