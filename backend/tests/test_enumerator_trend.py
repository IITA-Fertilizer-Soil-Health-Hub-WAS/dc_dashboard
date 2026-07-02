"""Per-enumerator flag-rate-over-time trend — catching degrading quality early."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.urls import reverse

from apps.kpi.metrics import enumerator_trend, project_quality_trend
from apps.rbac.models import Role, UseCaseMembership
from apps.submissions.models import Enumerator, Submission
from apps.usecases.models import FormDefinition, Organization, UseCase
from apps.validation.models import ValidationFlag, ValidationRule

pytestmark = pytest.mark.django_db


@pytest.fixture
def world():
    org = Organization.objects.create(code="o", name="O")
    uc = UseCase.objects.create(code="PROJ-A", name="A", organization=org)
    form = FormDefinition.objects.create(use_case=uc, ona_form_id=1,
                                         role=FormDefinition.Role.VALIDATION)
    enum = Enumerator.objects.create(use_case=uc, enid="E1")
    rule = ValidationRule.objects.create(
        use_case=uc, code="req", rule_type=ValidationRule.RuleType.REQUIRED_FIELD)
    return {"uc": uc, "form": form, "enum": enum, "rule": rule, "org": org}


def _sub(world, uuid, days_ago, flagged=False):
    s = Submission.objects.create(
        use_case=world["uc"], form=world["form"], ona_uuid=uuid, content_hash=uuid,
        enumerator=world["enum"], event_date=date.today() - timedelta(days=days_ago))
    if flagged:
        ValidationFlag.objects.create(
            submission=s, rule=world["rule"], message="missing", severity="WARNING",
            status=ValidationFlag.Status.OPEN)
    return s


def test_trend_flags_worsening_quality(world):
    # Earlier weeks clean, recent weeks all flagged → direction should be worsening.
    for i in range(4):
        _sub(world, f"old{i}", days_ago=70 + i, flagged=False)   # ~10 weeks ago
    for i in range(4):
        _sub(world, f"new{i}", days_ago=3 + i, flagged=True)     # this/last week

    t = enumerator_trend(world["uc"], world["enum"].id)
    assert t["direction"] == "worsening"
    assert t["early_pct"] == 0 and t["recent_pct"] == 100
    assert t["total_n"] == 8
    assert len(t["series"]) == t["weeks"]


def test_trend_improving_when_recent_is_cleaner(world):
    for i in range(4):
        _sub(world, f"old{i}", days_ago=70 + i, flagged=True)
    for i in range(4):
        _sub(world, f"new{i}", days_ago=3 + i, flagged=False)
    t = enumerator_trend(world["uc"], world["enum"].id)
    assert t["direction"] == "improving"


def test_project_quality_trend_detects_systemic_slide(world):
    # No enumerator attribution needed — the project-wide line still worsens.
    for i in range(4):
        s = Submission.objects.create(
            use_case=world["uc"], form=world["form"], ona_uuid=f"old{i}", content_hash=f"old{i}",
            event_date=date.today() - timedelta(days=70 + i))
        assert s  # clean
    for i in range(4):
        s = Submission.objects.create(
            use_case=world["uc"], form=world["form"], ona_uuid=f"new{i}", content_hash=f"new{i}",
            event_date=date.today() - timedelta(days=3 + i))
        ValidationFlag.objects.create(
            submission=s, rule=world["rule"], message="m", severity="WARNING",
            status=ValidationFlag.Status.OPEN)
    t = project_quality_trend(world["uc"])
    assert t["direction"] == "worsening"
    assert t["early_pct"] == 0 and t["recent_pct"] == 100 and t["total_n"] == 8


def test_enumerator_detail_view_renders(client, world, django_user_model):
    coord = django_user_model.objects.create_user(
        "c@x.org", "pw", is_active=True, organization=world["org"])
    UseCaseMembership.objects.create(user=coord, use_case=world["uc"], role=Role.TRIAL_COORDINATOR)
    _sub(world, "s1", days_ago=5, flagged=True)
    client.force_login(coord)
    resp = client.get(reverse("kpi:enumerator_detail", args=["PROJ-A", world["enum"].id]))
    assert resp.status_code == 200
    assert "Flag rate over time" in resp.content.decode()
