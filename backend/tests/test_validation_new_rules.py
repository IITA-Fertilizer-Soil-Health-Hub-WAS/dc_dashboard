"""New validation rules: cross-column, conditional-required, duplicate, and the
z-score / IQR statistical outlier variants."""
from __future__ import annotations

import pytest

from apps.projects.models import FormDefinition, Organization, Project
from apps.submissions.models import Submission, SubmissionValue
from apps.validation import rules
from apps.validation.engine import run_for_project
from apps.validation.models import ValidationFlag, ValidationRule

pytestmark = pytest.mark.django_db


@pytest.fixture
def project():
    org = Organization.objects.create(code="o", name="O")
    p = Project.objects.create(code="P", name="P", organization=org)
    FormDefinition.objects.create(project=p, ona_form_id=1, role=FormDefinition.Role.VALIDATION)
    return p


def _sub(project, uuid, values: dict):
    form = project.forms.first()
    s = Submission.objects.create(project=project, form=form, ona_uuid=uuid,
                                  content_hash=uuid)
    for k, v in values.items():
        SubmissionValue.objects.create(submission=s, field_key=k, raw_value=str(v),
                                       current_value=str(v))
    return s


# --- Cross-column (the "parts must sum to a whole" request) ------------------

def test_cross_field_sum_to_100(project):
    good = _sub(project, "ok", {"a": 50, "b": 30, "c": 20})   # sums to 100
    bad = _sub(project, "bad", {"a": 50, "b": 30, "c": 25})   # sums to 105
    params = {"fields": ["a", "b", "c"], "compare": "eq", "target": 100}
    fired = {r.submission_id for r in rules.cross_field(bad, params)}
    assert bad.id in fired
    assert not rules.cross_field(good, params)  # exact 100 passes


def test_cross_field_tolerance_and_partial(project):
    near = _sub(project, "near", {"a": 33.3, "b": 33.3, "c": 33.3})  # 99.9
    partial = _sub(project, "part", {"a": 50, "c": 20})  # b missing
    params = {"fields": ["a", "b", "c"], "target": 100, "tol": 0.5}
    assert not rules.cross_field(near, params)                 # within tolerance
    res = rules.cross_field(partial, params)
    assert res and "missing" in res[0].detail                 # partial entry surfaced


def test_cross_field_relation_between_fields(project):
    s = _sub(project, "rel", {"harvested": 120, "planted": 100})  # harvested > planted
    params = {"fields": ["harvested"], "compare": "lte", "rhs_fields": ["planted"]}
    assert rules.cross_field(s, params)  # 120 !<= 100 -> flagged


# --- Conditional required (skip-logic integrity) -----------------------------

def test_conditional_required(project):
    triggered = _sub(project, "t", {"fert_used": "yes"})       # type missing
    ok = _sub(project, "n", {"fert_used": "no"})               # condition off
    params = {"when": {"field": "fert_used", "equals": "yes"}, "require": ["fert_type"]}
    assert rules.conditional_required(triggered, params)
    assert not rules.conditional_required(ok, params)


# --- Duplicate detection -----------------------------------------------------

def test_unique_field_flags_duplicates(project):
    a = _sub(project, "a", {"barcode": "BC-1"})
    b = _sub(project, "b", {"barcode": "BC-1"})   # duplicate
    _sub(project, "c", {"barcode": "BC-2"})       # unique
    flagged = {r.submission_id for r in rules.unique_field(project, {"field": "barcode"})}
    assert flagged == {a.id, b.id}


# --- Statistical outliers: z-score (default) and IQR -------------------------

def test_numeric_outlier_zscore_and_iqr(project):
    for i in range(30):
        _sub(project, f"n{i}", {"yield": 100 + (i % 3)})   # tight cluster ~100
    _sub(project, "spike", {"yield": 900})                 # gross outlier
    z = rules.numeric_outlier(project, {"field": "yield", "z": 3.0, "min_n": 10})
    iqr = rules.numeric_outlier(project, {"field": "yield", "method": "iqr", "min_n": 10})
    assert any(r.detail["value"] == 900 for r in z)
    assert any(r.detail["value"] == 900 and r.detail["method"] == "iqr" for r in iqr)


def test_numeric_outlier_grouped_by_crop(project):
    # Two crops with very different normal ranges; a value normal for maize would
    # look like an outlier against the pooled distribution, but not within its crop.
    for i in range(25):
        _sub(project, f"rice{i}", {"yield": 10 + (i % 2), "crop": "rice"})
    for i in range(25):
        _sub(project, f"maize{i}", {"yield": 200 + (i % 2), "crop": "maize"})
    _sub(project, "bad_rice", {"yield": 90, "crop": "rice"})  # absurd for rice
    grouped = rules.numeric_outlier(project, {"field": "yield", "group_by": "crop",
                                              "z": 3.0, "min_n": 10})
    flagged_vals = {r.detail["value"] for r in grouped}
    assert 90 in flagged_vals  # caught within the rice group


# --- End-to-end through the engine (persists flags) --------------------------

def test_cross_field_rule_through_engine(project):
    _sub(project, "e_bad", {"a": 60, "b": 60})   # sums to 120, target 100
    ValidationRule.objects.create(
        project=project, code="parts_sum_100", rule_type="CROSS_FIELD",
        params={"fields": ["a", "b"], "target": 100}, severity="WARNING")
    run_for_project(project)
    assert ValidationFlag.objects.filter(rule__code="parts_sum_100",
                                         status=ValidationFlag.Status.OPEN).exists()
