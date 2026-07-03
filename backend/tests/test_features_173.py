"""Assignment+notifications, Issues filters, and the inline mapping editor."""
from __future__ import annotations

import pytest
from django.core import mail

from apps.projects.models import FieldMapping, FormDefinition, Project
from apps.rbac.models import Membership, Role
from apps.review import services
from apps.review.models import ReviewActionLog
from apps.submissions.models import Submission

pytestmark = pytest.mark.django_db


@pytest.fixture
def uc():
    return Project.objects.create(code="UC", name="UC")


@pytest.fixture
def form(uc):
    return FormDefinition.objects.create(project=uc, ona_form_id=1,
                                         role=FormDefinition.Role.VALIDATION)


@pytest.fixture
def coordinator(django_user_model, uc):
    u = django_user_model.objects.create_user("c@x.org", "pw", is_active=True)
    Membership.objects.create(user=u, project=uc, role=Role.TRIAL_COORDINATOR)
    return u


@pytest.fixture
def staff(django_user_model):
    return django_user_model.objects.create_superuser("admin@x.org", "pw")


# ---- Feature 1: assignment + notification ----
def test_assign_sets_assignee_logs_and_emails(uc, form, coordinator):
    sub = Submission.objects.create(project=uc, form=form, ona_uuid="u1", content_hash="h")
    services.assign(coordinator, sub, coordinator)
    sub.refresh_from_db()
    assert sub.review.assigned_to == coordinator
    assert ReviewActionLog.objects.filter(submission=sub, action="ASSIGN").exists()
    assert len(mail.outbox) == 1 and coordinator.email in mail.outbox[0].to


def test_assign_to_me_from_review_screen(client, uc, form, coordinator):
    sub = Submission.objects.create(project=uc, form=form, ona_uuid="u2", content_hash="h")
    client.force_login(coordinator)
    resp = client.post(f"/project/{uc.code}/submission/{sub.pk}/review/", {"action": "assign_me"})
    assert resp.status_code == 200
    sub.refresh_from_db()
    assert sub.review.assigned_to == coordinator


# ---- Feature 2: filters ----
def test_issues_filtered_by_search_and_state(client, uc, form, coordinator):
    from apps.validation.models import ValidationFlag, ValidationRule
    rule = ValidationRule.objects.create(project=uc, code="r", rule_type="REGEX_ID")
    s1 = Submission.objects.create(project=uc, form=form, ona_uuid="AAA", content_hash="h",
                                   event_key="Event1")
    s2 = Submission.objects.create(project=uc, form=form, ona_uuid="BBB", content_hash="h",
                                   event_key="Event2")
    ValidationFlag.objects.create(submission=s1, rule=rule, message="Check ENID", severity="ERROR")
    ValidationFlag.objects.create(submission=s2, rule=rule, message="Check HHID", severity="WARNING")
    client.force_login(coordinator)
    # filter by event (Issues table shows the flag message)
    resp = client.get(f"/project/{uc.code}/tab/issues/?event=Event1")
    assert b"Check ENID" in resp.content and b"Check HHID" not in resp.content
    # filter by severity
    resp = client.get(f"/project/{uc.code}/tab/issues/?severity=WARNING")
    assert b"Check HHID" in resp.content and b"Check ENID" not in resp.content


def test_issues_filters_survive_bulk_action(client, uc, form, coordinator):
    from apps.validation.models import ValidationFlag, ValidationRule
    rule = ValidationRule.objects.create(project=uc, code="r", rule_type="REGEX_ID")
    s = Submission.objects.create(project=uc, form=form, ona_uuid="KEEP", content_hash="h",
                                  event_key="Event9")
    ValidationFlag.objects.create(submission=s, rule=rule, message="x", severity="WARNING")
    client.force_login(coordinator)
    # a bulk action POST carrying the filter still renders within that filter
    resp = client.post(f"/project/{uc.code}/bulk-action/",
                       {"action": "OPEN_REVIEW", "ids": [str(s.pk)], "event": "Event9"})
    assert resp.status_code == 200
    assert b'value="Event9" selected' in resp.content  # filter preserved


# ---- Feature 3: inline mapping editor ----
def test_mapping_editor_renders(client, staff, form):
    client.force_login(staff)
    resp = client.get(f"/manage/forms/{form.pk}/mappings/")
    assert resp.status_code == 200
    assert b"Field mappings" in resp.content


def test_mapping_editor_creates_edits_deletes(client, staff, form):
    existing = FieldMapping.objects.create(form=form, target_field="OLD",
                                           source_paths=["a"], transform="DIRECT")
    client.force_login(staff)
    # edit existing 'OLD' -> 'ENID', and add a new HHID row
    resp = client.post(f"/manage/forms/{form.pk}/mappings/", {
        f"map-{existing.pk}-target": "ENID",
        f"map-{existing.pk}-source": "intro/enumerator_id",
        f"map-{existing.pk}-transform": "DIRECT",
        f"map-{existing.pk}-order": "0",
        "new-0-target": "HHID",
        "new-0-source": "intro/hh, intro/barcode",
        "new-0-transform": "COALESCE",
        "new-0-order": "1",
    })
    assert resp.status_code == 302
    existing.refresh_from_db()
    assert existing.target_field == "ENID"
    assert existing.source_paths == ["intro/enumerator_id"]
    hh = form.mappings.get(target_field="HHID")
    assert hh.source_paths == ["intro/hh", "intro/barcode"]
    assert hh.transform == "COALESCE"


def test_mapping_editor_delete(client, staff, form):
    m = FieldMapping.objects.create(form=form, target_field="DEL", source_paths=["x"])
    client.force_login(staff)
    client.post(f"/manage/forms/{form.pk}/mappings/", {f"map-{m.pk}-delete": "on"})
    assert not FieldMapping.objects.filter(pk=m.pk).exists()


def test_mapping_editor_staff_only(client, django_user_model, form):
    user = django_user_model.objects.create_user("u@x.org", "pw", is_active=True)
    client.force_login(user)
    assert client.get(f"/manage/forms/{form.pk}/mappings/").status_code == 403
