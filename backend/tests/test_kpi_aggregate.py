"""Feature C, Stage C1: daily KPI aggregation from submissions."""
from __future__ import annotations

from datetime import date

import pytest

from apps.kpi.aggregate import rebuild_all_kpis, rebuild_use_case_kpis
from apps.kpi.models import EnumeratorKpiDaily, FormKpiDaily, ProjectKpiDaily
from apps.submissions.models import Enumerator, Submission
from apps.usecases.models import FormDefinition, UseCase

pytestmark = pytest.mark.django_db


@pytest.fixture
def project():
    uc = UseCase.objects.create(code="UC", name="UC")
    form = FormDefinition.objects.create(use_case=uc, ona_form_id=1,
                                         role=FormDefinition.Role.VALIDATION)
    e1 = Enumerator.objects.create(use_case=uc, enid="EN1")
    e2 = Enumerator.objects.create(use_case=uc, enid="EN2")
    # Day 1: 2 submissions (e1, e2). Day 2: 1 submission (e1).
    Submission.objects.create(use_case=uc, form=form, ona_uuid="a", content_hash="h",
                              enumerator=e1, event_date=date(2026, 1, 1))
    Submission.objects.create(use_case=uc, form=form, ona_uuid="b", content_hash="h",
                              enumerator=e2, event_date=date(2026, 1, 1))
    Submission.objects.create(use_case=uc, form=form, ona_uuid="c", content_hash="h",
                              enumerator=e1, event_date=date(2026, 1, 2))
    return uc, form, e1, e2


def test_project_daily_counts(project):
    uc, *_ = project
    rebuild_use_case_kpis(uc)
    d1 = ProjectKpiDaily.objects.get(use_case=uc, date=date(2026, 1, 1))
    assert d1.submissions == 2
    assert d1.active_enumerators == 2
    d2 = ProjectKpiDaily.objects.get(use_case=uc, date=date(2026, 1, 2))
    assert d2.submissions == 1
    assert d2.active_enumerators == 1


def test_form_daily_counts(project):
    uc, form, *_ = project
    rebuild_use_case_kpis(uc)
    assert FormKpiDaily.objects.get(form=form, date=date(2026, 1, 1)).submissions == 2


def test_enumerator_daily_counts(project):
    uc, form, e1, e2 = project
    rebuild_use_case_kpis(uc)
    assert EnumeratorKpiDaily.objects.get(enumerator=e1, date=date(2026, 1, 1)).submissions == 1
    assert EnumeratorKpiDaily.objects.get(enumerator=e1, date=date(2026, 1, 2)).submissions == 1
    assert EnumeratorKpiDaily.objects.get(enumerator=e2, date=date(2026, 1, 1)).submissions == 1


def test_rebuild_is_idempotent(project):
    uc, *_ = project
    rebuild_use_case_kpis(uc)
    rebuild_use_case_kpis(uc)  # again — no duplicates
    assert ProjectKpiDaily.objects.filter(use_case=uc).count() == 2


def test_flags_opened_counted(project):
    uc, form, e1, e2 = project
    from apps.validation.models import ValidationFlag, ValidationRule
    rule = ValidationRule.objects.create(use_case=uc, code="R1",
                                         rule_type=ValidationRule.RuleType.REGEX_ID)
    sub = Submission.objects.get(ona_uuid="a")
    ValidationFlag.objects.create(submission=sub, rule=rule, message="x",
                                  severity=ValidationRule.Severity.ERROR)
    rebuild_use_case_kpis(uc)
    # The flag's created_at is today; assert the count lands on its day.
    total_flags = sum(p.flags_opened for p in ProjectKpiDaily.objects.filter(use_case=uc))
    assert total_flags == 1


def test_rebuild_all(project):
    uc, *_ = project
    UseCase.objects.create(code="EMPTY", name="Empty")  # no submissions
    totals = rebuild_all_kpis()
    assert totals["projects"] == 2
    assert totals["project_days"] == 2  # only UC has rows
