"""writeback_test management command — dry-run is safe (no submit)."""
from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.ingestion import writeback
from apps.ingestion.backends.odk import OdkBackend
from apps.review import services
from apps.submissions.models import Submission, SubmissionValue
from apps.usecases.models import FieldMapping, FormDefinition, Project

pytestmark = pytest.mark.django_db

INSTANCE = (
    '<data id="f"><intro><enumerator_id>EN1</enumerator_id></intro>'
    "<meta><instanceID>uuid:OLD</instanceID></meta></data>"
)


class FakeOdk(OdkBackend):
    supports_writeback = True
    submitted = None

    def _fetch_instance_xml(self, form_id, data_id):
        return INSTANCE

    def _submit_edited_xml(self, form_id, xml):
        FakeOdk.submitted = xml
        return "r1"


@pytest.fixture
def edited_submission(django_user_model, monkeypatch):
    admin = django_user_model.objects.create_superuser("a@x.org", "pw")
    uc = Project.objects.create(code="UC", name="UC")
    form = FormDefinition.objects.create(project=uc, ona_form_id=9,
                                         role=FormDefinition.Role.VALIDATION)
    FieldMapping.objects.create(form=form, target_field="ENID",
                                source_paths=["intro/enumerator_id"])
    sub = Submission.objects.create(project=uc, form=form, ona_uuid="u1",
                                    content_hash="h", ona_submission_id=42)
    SubmissionValue.objects.create(submission=sub, field_key="ENID",
                                   raw_value="EN1", current_value="EN1")
    services.edit_value(admin, sub, field_key="ENID", new_value="EN1-FIXED")
    monkeypatch.setattr(writeback, "get_backend_for", lambda uc: FakeOdk())
    # the command imports get_backend_for from registry; patch there too
    import apps.ingestion.management.commands.writeback_test as cmd
    monkeypatch.setattr(cmd, "get_backend_for", lambda uc: FakeOdk())
    FakeOdk.submitted = None
    return sub


def test_dry_run_does_not_submit(edited_submission):
    out = StringIO()
    call_command("writeback_test", str(edited_submission.pk), stdout=out)
    text = out.getvalue()
    assert "DRY RUN" in text
    assert "deprecatedID" in text and "uuid:OLD" in text
    assert "EN1-FIXED" in text  # edited value is in the produced XML
    assert FakeOdk.submitted is None  # nothing was sent


def test_commit_requires_enabled(edited_submission, settings):
    settings.WRITEBACK_ENABLED = False
    with pytest.raises(CommandError):
        call_command("writeback_test", str(edited_submission.pk), "--commit")


def test_commit_submits_when_enabled(edited_submission, settings):
    settings.WRITEBACK_ENABLED = True
    out = StringIO()
    call_command("writeback_test", str(edited_submission.pk), "--commit", stdout=out)
    edited_submission.refresh_from_db()
    assert edited_submission.writeback_status == Submission.WriteBackStatus.SENT
    assert FakeOdk.submitted is not None and "EN1-FIXED" in FakeOdk.submitted
