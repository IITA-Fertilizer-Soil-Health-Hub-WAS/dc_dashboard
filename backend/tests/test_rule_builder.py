"""Guided validation-rule builder: create/edit, scoping, and form-scoped rules."""
from __future__ import annotations

import json

import pytest
from django.urls import reverse

from apps.projects.models import FormDefinition, Organization, Project
from apps.rbac.models import Membership, Role
from apps.submissions.models import Submission, SubmissionValue
from apps.validation.engine import run_for_project
from apps.validation.models import ValidationFlag, ValidationRule

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    p = Project.objects.create(code="P", name="P", organization=org)
    f1 = FormDefinition.objects.create(project=p, ona_form_id=1, title="Reg",
                                       role=FormDefinition.Role.HH_REG)
    f2 = FormDefinition.objects.create(project=p, ona_form_id=2, title="Visit",
                                       role=FormDefinition.Role.VALIDATION)
    admin = django_user_model.objects.create_superuser("a@x.org", "pw")
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True,
                                                   organization=org)
    Membership.objects.create(user=coord, project=p, role=Role.TRIAL_COORDINATOR)
    return {"p": p, "f1": f1, "f2": f2, "admin": admin, "coord": coord}


def _login(client, user, project=None):
    client.force_login(user)
    if project:
        s = client.session
        s["active_project"] = project.code
        s.save()


def test_builder_renders(client, setup):
    _login(client, setup["admin"], setup["p"])
    resp = client.get(reverse("console:rule_new") + f"?project={setup['p'].code}")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "rb-settings" in body and "Applies to form" in body
    assert "fields-by-form" in body  # field lists embedded for the JS pickers


def test_builder_creates_form_scoped_rule(client, setup):
    _login(client, setup["admin"], setup["p"])
    params = json.dumps({"fields": ["a", "b"], "op": "sum", "compare": "eq", "target": 100})
    resp = client.post(
        reverse("console:rule_new") + f"?project={setup['p'].code}",
        {"code": "sum-100", "rule_type": "CROSS_FIELD", "severity": "WARNING",
         "form": str(setup["f2"].id), "is_enabled": "on", "params": params},
    )
    assert resp.status_code == 302
    rule = ValidationRule.objects.get(project=setup["p"], code="sum-100")
    assert rule.rule_type == "CROSS_FIELD" and rule.form_id == setup["f2"].id
    assert rule.params["target"] == 100


def test_builder_rejects_duplicate_code(client, setup):
    ValidationRule.objects.create(project=setup["p"], code="dup", rule_type="UNIQUE_FIELD",
                                  params={"field": "x"})
    _login(client, setup["admin"], setup["p"])
    resp = client.post(
        reverse("console:rule_new") + f"?project={setup['p'].code}",
        {"code": "dup", "rule_type": "UNIQUE_FIELD", "severity": "WARNING", "params": "{}"},
    )
    assert resp.status_code == 200 and "already exists" in resp.content.decode()


def test_builder_edit_scoped_to_visible_projects(client, setup, django_user_model):
    other = Project.objects.create(code="OTHER", name="Other")
    orule = ValidationRule.objects.create(project=other, code="x", rule_type="UNIQUE_FIELD",
                                          params={"field": "x"})
    _login(client, setup["coord"], setup["p"])
    # A coordinator can't open a rule from a project they can't see.
    assert client.get(reverse("console:rule_edit", args=[orule.pk])).status_code == 404


def _sub(project, form, uuid, values):
    s = Submission.objects.create(project=project, form=form, ona_uuid=uuid, content_hash=uuid)
    for k, v in values.items():
        SubmissionValue.objects.create(submission=s, field_key=k, raw_value=str(v),
                                       current_value=str(v))
    return s


def test_field_choices_from_schema_labels_notes_filtered(setup):
    from apps.console.views import _form_field_choices

    f = setup["f2"]
    f.field_schema = [
        {"path": "grp/note1", "label": "<b>Big note</b>", "type": "note"},   # dropped
        {"path": "grp/yield", "label": "Yield (kg/ha)", "type": "integer"},
    ]
    f.save(update_fields=["field_schema"])
    choices = _form_field_choices(f)
    keys = {c["key"]: c["label"] for c in choices}
    assert "grp/note1" not in keys                 # display-only note excluded
    assert keys["grp/yield"] == "Yield (kg/ha)"    # real field, human label


def test_rule_test_preview_counts(client, setup):
    """The Test button previews the flag count without saving a rule."""
    p = setup["p"]
    _sub(p, setup["f2"], "d1", {"barcode": "X"})
    _sub(p, setup["f2"], "d2", {"barcode": "X"})   # duplicate
    _sub(p, setup["f2"], "u1", {"barcode": "Y"})
    _login(client, setup["admin"], p)
    resp = client.post(reverse("console:rule_test"), {
        "project": p.code, "rule_type": "UNIQUE_FIELD", "form": str(setup["f2"].id),
        "params": json.dumps({"field": "barcode"})})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2 and data["scope"] == 3
    assert not ValidationRule.objects.filter(project=p).exists()  # nothing persisted


def test_rule_targets_raw_payload_field(setup):
    """A rule can target a raw form field (from raw_payload) even with no mapping."""
    from apps.validation import rules

    p = setup["p"]
    s = Submission.objects.create(project=p, form=setup["f2"], ona_uuid="r1",
                                  content_hash="r1", raw_payload={"grp/qty": "7"})
    # No SubmissionValue for grp/qty — value_of must fall back to raw_payload.
    assert rules.value_of(s, "grp/qty") == "7"
    fired = rules.numeric_range(s, {"field": "grp/qty", "min": 10, "max": 20})
    assert fired and fired[0].detail["value"] == 7


def test_form_scoped_rule_ignores_other_forms(client, setup):
    """A REQUIRED_FIELD rule bound to form f2 must not flag f1's submissions."""
    p = setup["p"]
    a = _sub(p, setup["f2"], "visit1", {"other": "1"})   # missing 'yield' → should flag
    b = _sub(p, setup["f1"], "reg1", {"name": "x"})       # different form → must NOT flag
    ValidationRule.objects.create(
        project=p, form=setup["f2"], code="need-yield", rule_type="REQUIRED_FIELD",
        params={"fields": ["yield"]}, severity="ERROR")
    run_for_project(p)
    flagged = set(ValidationFlag.objects.filter(rule__code="need-yield")
                  .values_list("submission_id", flat=True))
    assert a.id in flagged and b.id not in flagged
