"""Org overview, scheduled review digests, and backend connection test."""
from __future__ import annotations

from io import StringIO

import pytest
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.projects.models import DataSource, FormDefinition, Project
from apps.rbac.models import Role, UseCaseMembership
from apps.review.digests import send_review_digests
from apps.submissions.models import Submission

pytestmark = pytest.mark.django_db


@pytest.fixture
def uc():
    return Project.objects.create(code="UC", name="UC Name")


@pytest.fixture
def form(uc):
    return FormDefinition.objects.create(project=uc, ona_form_id=1,
                                         role=FormDefinition.Role.VALIDATION)


@pytest.fixture
def coordinator(django_user_model, uc):
    u = django_user_model.objects.create_user("c@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=u, project=uc, role=Role.TRIAL_COORDINATOR)
    return u


# ---- Overview ----
def test_overview_aggregates(client, uc, form, coordinator):
    Submission.objects.create(project=uc, form=form, ona_uuid="o1", content_hash="h")
    Submission.objects.create(project=uc, form=form, ona_uuid="o2", content_hash="h")
    client.force_login(coordinator)
    resp = client.get("/overview/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "UC Name" in body and "Overview" in body
    assert "2" in body  # 2 submissions counted


# ---- Digest ----
def test_digest_emails_reviewers_with_pending(uc, form, coordinator):
    Submission.objects.create(project=uc, form=form, ona_uuid="p1", content_hash="h")  # in review
    sent = send_review_digests()
    assert sent == 1
    assert len(mail.outbox) == 1
    assert coordinator.email in mail.outbox[0].to
    assert uc.code in mail.outbox[0].subject


def test_digest_skips_when_nothing_pending(uc, form, coordinator):
    # No submissions -> nothing pending -> no email.
    assert send_review_digests() == 0
    assert mail.outbox == []


def test_digest_skips_project_without_reviewers(uc, form):
    Submission.objects.create(project=uc, form=form, ona_uuid="p1", content_hash="h")
    # No coordinator/QC members -> no recipients.
    assert send_review_digests() == 0


# ---- Connection test command ----
def test_connection_command_reports_projects(uc, monkeypatch):
    DataSource.objects.create(project=uc, backend="ONA", token="t")

    import apps.ingestion.management.commands.test_connection as cmd
    from apps.ingestion.backends.base import RemoteForm, RemoteProject

    class FakeBackend:
        label = "ONA / ODK"
        type = "ONA"
        base_url = "https://api.ona.io"
        supports_discovery = True

        def discover_projects(self):
            return [RemoteProject(id="1", name="Proj", forms=[RemoteForm(id="9", title="F")])]

    monkeypatch.setattr(cmd, "get_backend_for", lambda uc: FakeBackend())
    out = StringIO()
    call_command("test_connection", "UC", stdout=out)
    assert "Discovered 1 project(s)" in out.getvalue()


def test_connection_command_reports_failure(uc, monkeypatch):
    import apps.ingestion.management.commands.test_connection as cmd

    class FailBackend:
        label = "Kobo"
        type = "KOBO"
        base_url = ""
        supports_discovery = True

        def discover_projects(self):
            raise RuntimeError("401 Unauthorized")

    monkeypatch.setattr(cmd, "get_backend_for", lambda uc: FailBackend())
    with pytest.raises(CommandError):
        call_command("test_connection", "UC")
