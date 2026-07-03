"""Alert when an enumerator's quality trend crosses into 'worsening'."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from apps.kpi.alerts import evaluate_rule_for_project, run_alerts
from apps.kpi.models import AlertEvent, AlertRule
from apps.projects.models import FormDefinition, Organization, Project
from apps.submissions.models import Enumerator, Submission
from apps.validation.models import ValidationFlag, ValidationRule

pytestmark = pytest.mark.django_db


@pytest.fixture
def world():
    org = Organization.objects.create(code="o", name="O")
    uc = Project.objects.create(code="PROJ-A", name="A", organization=org)
    form = FormDefinition.objects.create(project=uc, ona_form_id=1,
                                         role=FormDefinition.Role.VALIDATION)
    rule = ValidationRule.objects.create(
        project=uc, code="req", rule_type=ValidationRule.RuleType.REQUIRED_FIELD)
    return {"uc": uc, "form": form, "vrule": rule}


def _sub(world, enum, uuid, days_ago, flagged):
    s = Submission.objects.create(
        project=world["uc"], form=world["form"], ona_uuid=uuid, content_hash=uuid,
        enumerator=enum, event_date=date.today() - timedelta(days=days_ago))
    if flagged:
        ValidationFlag.objects.create(
            submission=s, rule=world["vrule"], message="m", severity="WARNING",
            status=ValidationFlag.Status.OPEN)
    return s


def _make_worsening(world, enid):
    enum = Enumerator.objects.create(project=world["uc"], enid=enid)
    for i in range(5):  # earlier weeks clean
        _sub(world, enum, f"{enid}-old{i}", 70 + i, flagged=False)
    for i in range(5):  # recent weeks flagged → worsening, volume ≥ 8
        _sub(world, enum, f"{enid}-new{i}", 3 + i, flagged=True)
    return enum


def _rule(world):
    return AlertRule.objects.create(
        project=world["uc"], name="Quality degrading",
        metric="worsening_enumerators",
        comparator=AlertRule.Comparator.GTE, threshold=1,
        notify_emails=["coord@x.org"])


def test_alert_fires_and_names_the_enumerator(world):
    _make_worsening(world, "EN-BAD")
    event = evaluate_rule_for_project(_rule(world), world["uc"])
    assert event is not None
    assert "EN-BAD" in event.message and "0%→100%" in event.message


def test_no_alert_when_nobody_worsening(world):
    enum = Enumerator.objects.create(project=world["uc"], enid="EN-OK")
    for i in range(8):  # steady, clean
        _sub(world, enum, f"ok{i}", 5 + i, flagged=False)
    assert evaluate_rule_for_project(_rule(world), world["uc"]) is None


def test_low_volume_worsening_is_ignored(world):
    enum = Enumerator.objects.create(project=world["uc"], enid="EN-TINY")
    _sub(world, enum, "old", 70, flagged=False)
    _sub(world, enum, "new", 3, flagged=True)  # only 2 subs — below MIN_TREND_VOLUME
    assert evaluate_rule_for_project(_rule(world), world["uc"]) is None


def test_project_quality_worsening_alert(world):
    # A systemic slide (no per-enumerator attribution) fires the project alert.
    for i in range(4):
        Submission.objects.create(
            project=world["uc"], form=world["form"], ona_uuid=f"o{i}", content_hash=f"o{i}",
            event_date=date.today() - timedelta(days=70 + i))
    for i in range(4):
        s = Submission.objects.create(
            project=world["uc"], form=world["form"], ona_uuid=f"n{i}", content_hash=f"n{i}",
            event_date=date.today() - timedelta(days=3 + i))
        ValidationFlag.objects.create(
            submission=s, rule=world["vrule"], message="m", severity="WARNING",
            status=ValidationFlag.Status.OPEN)
    rule = AlertRule.objects.create(
        project=world["uc"], name="Project slide", metric="project_quality_worsening",
        comparator=AlertRule.Comparator.GTE, threshold=1)
    event = evaluate_rule_for_project(rule, world["uc"])
    assert event is not None and "0%→100%" in event.message


def test_run_alerts_emails_watchers(world, mailoutbox):
    _make_worsening(world, "EN-BAD")
    _rule(world)
    result = run_alerts()
    assert result["events"] == 1 and result["emails"] == 1
    assert "coord@x.org" in mailoutbox[0].to
    assert AlertEvent.objects.count() == 1
    # Idempotent: a second run the same day does not re-fire.
    assert run_alerts()["events"] == 0
