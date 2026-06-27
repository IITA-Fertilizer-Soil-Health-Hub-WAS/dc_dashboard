"""Review screen shows ALL submitted form fields (from the raw server record)."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.dashboards.views import _raw_submission_fields
from apps.rbac.models import Role, UseCaseMembership
from apps.submissions.models import Submission
from apps.usecases.models import FormDefinition, Organization, UseCase

pytestmark = pytest.mark.django_db


def test_raw_fields_keeps_answers_drops_system():
    payload = {
        "_id": 1, "_uuid": "x", "_geolocation": [1, 2], "meta/instanceID": "i",
        "today": "2024-01-01", "deviceid": "d", "__version__": "v",
        "C_identity/first_name": "Ama", "soil_ph": "6.5",
        "repeat_crops": [{"crop": "maize"}],
    }
    fields = _raw_submission_fields(payload)
    keys = {f["key"] for f in fields}
    assert "C_identity/first_name" in keys and "soil_ph" in keys
    assert "_id" not in keys and "meta/instanceID" not in keys and "today" not in keys
    # Nested repeat/group is serialised, not dropped.
    repeat = next(f for f in fields if f["key"] == "repeat_crops")
    assert "maize" in repeat["value"]


def test_review_page_lists_all_submitted_fields(client, django_user_model):
    org = Organization.objects.create(code="o", name="O")
    uc = UseCase.objects.create(code="PROJ-A", name="A", organization=org)
    form = FormDefinition.objects.create(use_case=uc, ona_form_id=1, role=FormDefinition.Role.VALIDATION)
    sub = Submission.objects.create(
        use_case=uc, form=form, ona_uuid="u1", content_hash="h",
        raw_payload={"_id": 5, "section/soil_colour": "dark", "yield_kg": "120"},
    )
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True, organization=org)
    UseCaseMembership.objects.create(user=coord, use_case=uc, role=Role.TRIAL_COORDINATOR)
    client.force_login(coord)
    resp = client.get(reverse("dashboards:submission_review", args=["PROJ-A", sub.id]))
    assert resp.status_code == 200
    assert b"All submitted fields" in resp.content
    assert b"section/soil_colour" in resp.content and b"yield_kg" in resp.content
    assert b"_id" not in resp.content.split(b"All submitted fields")[1]  # system field hidden
