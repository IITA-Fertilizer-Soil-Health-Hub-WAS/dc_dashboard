"""Submission location: the server's geodata lands on the submission and maps."""
from __future__ import annotations

from datetime import UTC

import pytest
from django.urls import reverse

from apps.ingestion.sync import submission_location
from apps.rbac.models import Role, UseCaseMembership
from apps.submissions.models import Enumerator, Submission
from apps.usecases.models import FormDefinition, Organization, UseCase

pytestmark = pytest.mark.django_db


def test_location_from_ona_geolocation():
    lat, lon = submission_location({"_geolocation": [-1.95, 30.06]}, {})
    assert lat == -1.95 and lon == 30.06


def test_location_falls_back_to_mapped_geopoint():
    lat, lon = submission_location({}, {"LAT": "-1.5", "LON": "29.9"})
    assert lat == -1.5 and lon == 29.9


def test_no_location_returns_none():
    assert submission_location({"_geolocation": [None, None]}, {}) == (None, None)
    assert submission_location({}, {}) == (None, None)


@pytest.fixture
def world(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    uc = UseCase.objects.create(code="PROJ-A", name="A", organization=org)
    form = FormDefinition.objects.create(use_case=uc, ona_form_id=9, role=FormDefinition.Role.VALIDATION)
    en = Enumerator.objects.create(use_case=uc, enid="EN-1")
    Submission.objects.create(use_case=uc, form=form, ona_uuid="g1", content_hash="h",
                              enumerator=en, lat="-1.95", lon="30.06")
    Submission.objects.create(use_case=uc, form=form, ona_uuid="g2", content_hash="h",
                              enumerator=en)  # no geo
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True, organization=org)
    UseCaseMembership.objects.create(user=coord, use_case=uc, role=Role.TRIAL_COORDINATOR)
    return {"uc": uc, "coord": coord}


def test_summary_map_plots_submission_points(client, world):
    client.force_login(world["coord"])
    resp = client.get(reverse("dashboards:tab_summary", args=["PROJ-A"]))
    assert resp.status_code == 200
    assert resp.context["mapped_points"] == 1            # one submission has geo
    assert b"Submissions by location" in resp.content
    assert b"1 mapped" in resp.content


def test_trend_uses_submission_time_when_no_event_date(django_user_model):
    from datetime import datetime

    from apps.dashboards.charts import _effective_date

    org = Organization.objects.create(code="o2", name="O2")
    uc = UseCase.objects.create(code="P2", name="P2", organization=org)
    form = FormDefinition.objects.create(use_case=uc, ona_form_id=3, role=FormDefinition.Role.VALIDATION)
    # No event_date, but a server submission_time — the trend must still place it.
    s = Submission.objects.create(use_case=uc, form=form, ona_uuid="t1", content_hash="h",
                                  ona_submission_time=datetime(2024, 6, 15, 9, 0, tzinfo=UTC))
    assert _effective_date(s).strftime("%Y-%m") == "2024-06"
