"""Review screen shows ALL submitted form fields (from the raw server record)."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.dashboards.views import _merged_fields, _raw_field_map
from apps.rbac.models import Role, UseCaseMembership
from apps.submissions.models import Submission, SubmissionValue
from apps.usecases.models import FormDefinition, Organization, Project

pytestmark = pytest.mark.django_db


def test_raw_field_map_keeps_answers_drops_system():
    payload = {
        "_id": 1, "_uuid": "x", "_geolocation": [1, 2], "meta/instanceID": "i",
        "today": "2024-01-01", "deviceid": "d", "__version__": "v",
        "C_identity/first_name": "Ama", "soil_ph": "6.5",
        "repeat_crops": [{"crop": "maize"}],
    }
    fm = _raw_field_map(payload)
    assert "C_identity/first_name" in fm and "soil_ph" in fm
    assert "_id" not in fm and "meta/instanceID" not in fm and "today" not in fm
    assert "maize" in fm["repeat_crops"]   # nested serialised, not dropped


def test_merged_fields_overlays_edits_on_raw():
    org = Organization.objects.create(code="o0", name="O")
    uc = Project.objects.create(code="PX", name="X", organization=org)
    form = FormDefinition.objects.create(project=uc, ona_form_id=1, role=FormDefinition.Role.VALIDATION)
    sub = Submission.objects.create(project=uc, form=form, ona_uuid="u0", content_hash="h",
                                    raw_payload={"soil_ph": "6.5", "grp/crop": "maize"})
    SubmissionValue.objects.create(submission=sub, field_key="soil_ph",
                                   raw_value="6.5", current_value="7.0", is_edited=True)
    fields = {f["key"]: f for f in _merged_fields(sub)}
    assert fields["soil_ph"]["current"] == "7.0" and fields["soil_ph"]["is_edited"]
    assert fields["grp/crop"]["current"] == "maize"   # un-edited raw field, editable


def test_review_lists_and_edits_any_field(client, django_user_model):
    org = Organization.objects.create(code="o", name="O")
    uc = Project.objects.create(code="PROJ-A", name="A", organization=org)
    form = FormDefinition.objects.create(project=uc, ona_form_id=1, role=FormDefinition.Role.VALIDATION)
    sub = Submission.objects.create(
        project=uc, form=form, ona_uuid="u1", content_hash="h",
        raw_payload={"_id": 5, "section/soil_colour": "dark", "yield_kg": "120"},
    )
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True, organization=org)
    UseCaseMembership.objects.create(user=coord, project=uc, role=Role.TRIAL_COORDINATOR)
    client.force_login(coord)
    url = reverse("dashboards:submission_review", args=["PROJ-A", sub.id])
    resp = client.get(url)
    assert resp.status_code == 200
    assert b"section/soil_colour" in resp.content and b"yield_kg" in resp.content
    assert b'name="val-section/soil_colour"' in resp.content   # raw field is editable
    # Edit an unmapped raw field — a tracked value is created for it.
    client.post(url, {"action": "save_edits", "val-yield_kg": "200",
                      "val-section/soil_colour": "dark"})
    sv = SubmissionValue.objects.get(submission=sub, field_key="yield_kg")
    assert sv.current_value == "200"
    # The unchanged field did NOT create a spurious edit.
    assert not SubmissionValue.objects.filter(submission=sub, field_key="section/soil_colour").exists()
