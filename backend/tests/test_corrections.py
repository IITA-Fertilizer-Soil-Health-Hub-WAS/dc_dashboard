"""The field feedback loop: an enumerator sees and is emailed the open issues on
the data they collected."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.projects.models import FormDefinition, Organization, Project
from apps.review.corrections import open_corrections, send_correction_digests
from apps.submissions.models import Submission
from apps.validation.models import ValidationFlag, ValidationRule

pytestmark = pytest.mark.django_db


@pytest.fixture
def flagged(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    p = Project.objects.create(code="P", name="P", organization=org)
    f = FormDefinition.objects.create(project=p, ona_form_id=1,
                                      role=FormDefinition.Role.VALIDATION)
    user = django_user_model.objects.create_user("e@x.org", "pw", is_active=True)
    other = django_user_model.objects.create_user("o@x.org", "pw", is_active=True)
    s = Submission.objects.create(project=p, form=f, ona_uuid="u1", content_hash="h1",
                                  collected_by=user)
    # A submission collected by someone else — must NOT appear in this user's list.
    s2 = Submission.objects.create(project=p, form=f, ona_uuid="u2", content_hash="h2",
                                   collected_by=other)
    rule = ValidationRule.objects.create(project=p, code="r", rule_type="REQUIRED_FIELD",
                                         params={}, severity="WARNING")
    flag = ValidationFlag.objects.create(submission=s, rule=rule, field_key="yield",
                                         message="Missing yield", severity="WARNING",
                                         status=ValidationFlag.Status.OPEN)
    ValidationFlag.objects.create(submission=s2, rule=rule, field_key="yield",
                                  message="Other's issue", severity="WARNING",
                                  status=ValidationFlag.Status.OPEN)
    return {"p": p, "user": user, "flag": flag}


def test_open_corrections_scoped_to_collector(flagged):
    flags = list(open_corrections(flagged["user"]))
    assert flagged["flag"] in flags
    assert all("Other" not in f.message for f in flags)  # not another collector's


def test_correction_digest_emails_the_enumerator(flagged, monkeypatch):
    sent = []
    monkeypatch.setattr("apps.review.corrections.send_safe_email",
                        lambda subj, body, rcpts, **k: sent.append((rcpts, body)) or True)
    n = send_correction_digests()
    assert n == 2  # both collectors with open flags are emailed
    mine = [body for rcpts, body in sent if rcpts == ["e@x.org"]]
    assert mine and "Missing yield" in mine[0] and "Other's issue" not in mine[0]


def test_my_submissions_lists_the_specific_issues(client, flagged):
    client.force_login(flagged["user"])
    resp = client.get(reverse("dashboards:my_submissions"))
    assert resp.status_code == 200
    assert "Missing yield" in resp.content.decode()  # the actual issue, not just a count
