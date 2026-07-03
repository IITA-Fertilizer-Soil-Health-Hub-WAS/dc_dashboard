"""Feature C, Stage C4: M&E threshold-alert engine + email + in-app feed."""
from __future__ import annotations

from datetime import date

import pytest
from django.core import mail
from django.urls import reverse

from apps.kpi.aggregate import rebuild_project_kpis
from apps.kpi.alerts import evaluate_rule_for_project, run_alerts
from apps.kpi.models import AlertEvent, AlertRule
from apps.projects.models import FormDefinition, Organization, Project
from apps.rbac.models import Membership, Role
from apps.submissions.models import Enumerator, Submission
from apps.validation.models import ValidationFlag, ValidationRule

pytestmark = pytest.mark.django_db


def _seed_submissions(uc, n, on=None):
    form = FormDefinition.objects.create(project=uc, ona_form_id=7,
                                         role=FormDefinition.Role.VALIDATION)
    en = Enumerator.objects.create(project=uc, enid="EN-1")
    for i in range(n):
        Submission.objects.create(project=uc, form=form, ona_uuid=f"s-{i}",
                                  content_hash="h", enumerator=en,
                                  event_date=on or date.today())
    rebuild_project_kpis(uc)
    return form, en


@pytest.fixture
def org():
    return Organization.objects.create(code="o", name="O")


def test_daily_submissions_low_volume_fires(org):
    uc = Project.objects.create(code="PA", name="PA", organization=org)
    _seed_submissions(uc, 1)  # 1 submission today, below threshold of 5
    rule = AlertRule.objects.create(
        project=uc, name="Low volume", metric="daily_submissions",
        comparator=AlertRule.Comparator.LT, threshold=5, consecutive_days=1,
        severity=AlertRule.Severity.WARNING,
    )
    ev = evaluate_rule_for_project(rule, uc)
    assert ev is not None
    assert ev.observed_value == 1
    assert ev.severity == AlertRule.Severity.WARNING


def test_threshold_not_breached_no_event(org):
    uc = Project.objects.create(code="PB", name="PB", organization=org)
    _seed_submissions(uc, 10)  # above threshold
    rule = AlertRule.objects.create(
        project=uc, name="Low volume", metric="daily_submissions",
        comparator=AlertRule.Comparator.LT, threshold=5,
    )
    assert evaluate_rule_for_project(rule, uc) is None


def test_idempotent_same_day(org):
    uc = Project.objects.create(code="PC", name="PC", organization=org)
    _seed_submissions(uc, 0)
    rule = AlertRule.objects.create(
        project=uc, name="Silent", metric="daily_submissions",
        comparator=AlertRule.Comparator.LTE, threshold=0,
    )
    assert evaluate_rule_for_project(rule, uc) is not None
    # Already fired today → no duplicate.
    assert evaluate_rule_for_project(rule, uc) is None
    assert AlertEvent.objects.filter(rule=rule).count() == 1


def test_open_flags_metric(org):
    uc = Project.objects.create(code="PD", name="PD", organization=org)
    form, en = _seed_submissions(uc, 2)
    vr = ValidationRule.objects.create(project=uc, code="r",
                                       rule_type=ValidationRule.RuleType.REGEX_ID,
                                       severity=ValidationRule.Severity.ERROR)
    sub = Submission.objects.filter(project=uc).first()
    ValidationFlag.objects.create(submission=sub, rule=vr, message="x",
                                  severity=ValidationRule.Severity.ERROR,
                                  status=ValidationFlag.Status.OPEN)
    rule = AlertRule.objects.create(
        project=uc, name="Too many issues", metric="open_flags",
        comparator=AlertRule.Comparator.GTE, threshold=1,
    )
    ev = evaluate_rule_for_project(rule, uc)
    assert ev is not None and ev.observed_value == 1


def test_run_alerts_emails_watchers(org):
    uc = Project.objects.create(code="PE", name="PE", organization=org)
    _seed_submissions(uc, 0)
    AlertRule.objects.create(
        project=uc, name="Silent", metric="daily_submissions",
        comparator=AlertRule.Comparator.LTE, threshold=0,
        notify_emails=["watch@x.org"],
    )
    result = run_alerts()
    assert result["events"] == 1
    assert result["emails"] == 1
    assert len(mail.outbox) == 1
    assert "watch@x.org" in mail.outbox[0].to


def test_platform_wide_rule_evaluates_all_projects(org):
    a = Project.objects.create(code="PF", name="PF", organization=org)
    b = Project.objects.create(code="PG", name="PG", organization=org)
    _seed_submissions(a, 0)
    _seed_submissions(b, 0)
    AlertRule.objects.create(  # project null = platform-wide
        name="Any silent project", metric="daily_submissions",
        comparator=AlertRule.Comparator.LTE, threshold=0,
    )
    result = run_alerts()
    assert result["events"] == 2


def test_alerts_view_scoped(client, django_user_model, org):
    uc = Project.objects.create(code="PH", name="PH", organization=org)
    other = Project.objects.create(code="PZ", name="PZ", organization=org)
    rule_a = AlertRule.objects.create(project=uc, name="A", metric="open_flags")
    rule_z = AlertRule.objects.create(project=other, name="Z", metric="open_flags")
    AlertEvent.objects.create(rule=rule_a, project=uc, severity="WARNING",
                              message="visible alert", observed_value=0)
    AlertEvent.objects.create(rule=rule_z, project=other, severity="WARNING",
                              message="hidden alert", observed_value=0)
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True,
                                                   organization=org)
    Membership.objects.create(user=coord, project=uc, role=Role.TRIAL_COORDINATOR)
    client.force_login(coord)
    resp = client.get(reverse("kpi:alerts"))
    assert resp.status_code == 200
    assert b"visible alert" in resp.content
    assert b"hidden alert" not in resp.content
