"""SDMT-inspired #3: per-submission distance-to-assigned-plot spatial QC."""
from __future__ import annotations

import pytest

from apps.common.geo import haversine_m
from apps.dashboards.charts import submission_plot_map_html
from apps.fieldwork.models import CollectionUnit
from apps.rbac.models import Role, UseCaseMembership
from apps.submissions.models import Submission
from apps.usecases.models import FormDefinition, Organization, UseCase
from apps.validation.engine import run_for_use_case
from apps.validation.models import ValidationFlag, ValidationRule

pytestmark = pytest.mark.django_db


def test_haversine_known_distance():
    # Nairobi CBD area: ~157 m between two close points.
    d = haversine_m(-1.2921, 36.8219, -1.2921, 36.8233)
    assert 150 < d < 165
    assert haversine_m(None, 1, 2, 3) is None


@pytest.fixture
def world():
    org = Organization.objects.create(code="o", name="O")
    uc = UseCase.objects.create(code="PROJ-A", name="A", organization=org)
    form = FormDefinition.objects.create(use_case=uc, ona_form_id=1,
                                         role=FormDefinition.Role.VALIDATION)
    unit = CollectionUnit.objects.create(use_case=uc, code="U1",
                                         lat="-1.2921", lon="36.8219")
    return {"uc": uc, "form": form, "unit": unit}


def _sub(world, lat, lon, uuid, unit=True):
    return Submission.objects.create(
        use_case=world["uc"], form=world["form"], ona_uuid=uuid, content_hash="h",
        lat=lat, lon=lon, collection_unit=world["unit"] if unit else None)


def test_distance_property(world):
    near = _sub(world, "-1.2921", "36.8219", "n")  # same as unit
    far = _sub(world, "-1.3100", "36.8500", "f")   # a few km off
    assert near.distance_to_unit_m < 1
    assert far.distance_to_unit_m > 2000
    assert _sub(world, None, None, "nogps").distance_to_unit_m is None


def test_geo_distance_rule_flags_far_submissions(world):
    ValidationRule.objects.create(
        use_case=world["uc"], code="too-far", rule_type=ValidationRule.RuleType.GEO_DISTANCE,
        params={"max_m": 100}, severity=ValidationRule.Severity.WARNING)
    near = _sub(world, "-1.2921", "36.8219", "n")
    far = _sub(world, "-1.3100", "36.8500", "f")
    run_for_use_case(world["uc"])
    assert not ValidationFlag.objects.filter(submission=near, status="OPEN").exists()
    flag = ValidationFlag.objects.get(submission=far, status="OPEN")
    assert "from assigned plot" in flag.message
    assert flag.detail["distance_m"] > 100


def test_no_flag_without_coordinates(world):
    ValidationRule.objects.create(
        use_case=world["uc"], code="too-far", rule_type=ValidationRule.RuleType.GEO_DISTANCE,
        params={"max_m": 100})
    _sub(world, None, None, "nogps")
    run_for_use_case(world["uc"])
    assert ValidationFlag.objects.filter(status="OPEN").count() == 0


def test_plot_map_renders_when_coords_present(world):
    far = _sub(world, "-1.3100", "36.8500", "f")
    html = submission_plot_map_html(far)
    assert "folium" in html.lower() or "leaflet" in html.lower()
    # No coords anywhere → empty string, no map.
    bare = _sub(world, None, None, "bare", unit=False)
    assert submission_plot_map_html(bare) == ""


def test_review_screen_shows_distance_badge(client, world, django_user_model):
    far = _sub(world, "-1.3100", "36.8500", "f")
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True,
                                                   organization=world["uc"].organization)
    UseCaseMembership.objects.create(user=coord, use_case=world["uc"],
                                     role=Role.TRIAL_COORDINATOR)
    client.force_login(coord)
    from django.urls import reverse
    page = client.get(reverse("dashboards:submission_review",
                              args=["PROJ-A", far.id])).content
    assert b"from plot" in page and b"assigned plot" in page
