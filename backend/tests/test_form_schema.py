"""SDMT-inspired #1: labelled + grouped submission rendering from the form schema."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.ingestion.form_schema import flatten_children, label_map, parse_form_json
from apps.rbac.models import Role, UseCaseMembership
from apps.submissions.models import Submission
from apps.usecases.models import FormDefinition, Organization, UseCase

pytestmark = pytest.mark.django_db


SAMPLE_FORM = {
    "children": [
        {"name": "A_plot", "type": "group", "label": "Plot details", "children": [
            {"name": "plot_id", "type": "text", "label": {"English (en)": "Plot ID"}},
            {"name": "crop", "type": "select one", "label": "Crop grown"},
        ]},
        {"name": "notes", "type": "text", "label": "Field notes"},
        {"name": "meta", "type": "group", "label": "", "children": [
            {"name": "instanceID", "type": "calculate"},
        ]},
    ]
}


def test_flatten_builds_paths_labels_and_groups():
    schema = parse_form_json(SAMPLE_FORM)
    by_path = {f["path"]: f for f in schema}
    assert by_path["A_plot/plot_id"]["label"] == "Plot ID"  # multi-language picked
    assert by_path["A_plot/plot_id"]["group"] == "Plot details"
    assert by_path["A_plot/crop"]["label"] == "Crop grown"
    assert by_path["notes"]["group"] == ""  # top-level, no section
    assert by_path["notes"]["label"] == "Field notes"


def test_flatten_falls_back_to_name_without_label():
    schema = flatten_children([{"name": "raw_q", "type": "text"}])
    assert schema[0]["label"] == "raw_q"


def test_label_map_shape():
    lm = label_map(parse_form_json(SAMPLE_FORM))
    assert lm["A_plot/crop"] == {"label": "Crop grown", "group": "Plot details"}


def test_review_screen_renders_labels_and_groups(client, django_user_model):
    org = Organization.objects.create(code="o", name="O")
    uc = UseCase.objects.create(code="PROJ-A", name="A", organization=org)
    form = FormDefinition.objects.create(
        use_case=uc, ona_form_id=1, role=FormDefinition.Role.VALIDATION,
        field_schema=parse_form_json(SAMPLE_FORM),
    )
    sub = Submission.objects.create(
        use_case=uc, form=form, ona_uuid="u1", content_hash="h",
        raw_payload={"A_plot/plot_id": "P-42", "A_plot/crop": "maize", "notes": "ok"},
    )
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True, organization=org)
    UseCaseMembership.objects.create(user=coord, use_case=uc, role=Role.TRIAL_COORDINATOR)
    client.force_login(coord)
    page = client.get(reverse("dashboards:submission_review", args=["PROJ-A", sub.id])).content
    assert b"Plot ID" in page and b"Crop grown" in page  # human labels
    assert b"Plot details" in page  # section header
    assert b"A_plot/plot_id" in page  # raw path still shown as sub-label
