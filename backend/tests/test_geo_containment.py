"""Plot election slice 4: GEO_CONTAINMENT rule + distance anchored to captured point."""
from __future__ import annotations

import pytest

from apps.fieldwork.anchor import capture_anchor
from apps.fieldwork.election import elect_candidate
from apps.fieldwork.models import CandidatePlot
from apps.projects.models import FormDefinition, Organization, Project
from apps.submissions.models import Submission
from apps.validation.engine import run_for_project
from apps.validation.models import ValidationFlag, ValidationRule

pytestmark = pytest.mark.django_db

SQUARE = {"type": "Polygon", "coordinates": [[
    [36.80, -1.29], [36.81, -1.29], [36.81, -1.28], [36.80, -1.28], [36.80, -1.29]]]}


@pytest.fixture
def world():
    org = Organization.objects.create(code="o", name="O")
    uc = Project.objects.create(code="PROJ-A", name="A", organization=org)
    form = FormDefinition.objects.create(project=uc, ona_form_id=1,
                                         role=FormDefinition.Role.VALIDATION)
    cand = CandidatePlot.objects.create(
        project=uc, trial_key="T1", candidate_ref="A", rank=1, geometry=SQUARE,
        centroid_lat=-1.285, centroid_lon=36.805)
    unit = elect_candidate(None, cand)
    return {"uc": uc, "form": form, "unit": unit}


def _sub(world, lat, lon, uuid):
    return Submission.objects.create(
        project=world["uc"], form=world["form"], ona_uuid=uuid, content_hash="h",
        lat=lat, lon=lon, collection_unit=world["unit"])


def test_containment_flags_only_outside(world):
    ValidationRule.objects.create(
        project=world["uc"], code="in-plot",
        rule_type=ValidationRule.RuleType.GEO_CONTAINMENT)
    inside = _sub(world, "-1.285", "36.805", "in")
    outside = _sub(world, "-1.35", "36.805", "out")
    run_for_project(world["uc"])
    assert not ValidationFlag.objects.filter(submission=inside, status="OPEN").exists()
    flag = ValidationFlag.objects.get(submission=outside, status="OPEN")
    assert flag.detail["outside_boundary"] is True


def test_no_flag_without_boundary_or_gps(world):
    world["unit"].boundary = {}
    world["unit"].save(update_fields=["boundary"])
    ValidationRule.objects.create(
        project=world["uc"], code="in-plot",
        rule_type=ValidationRule.RuleType.GEO_CONTAINMENT)
    _sub(world, "-1.35", "36.805", "out")           # outside, but no boundary now
    _sub(world, None, None, "nogps")                # no GPS
    run_for_project(world["uc"])
    assert ValidationFlag.objects.filter(status="OPEN").count() == 0


def test_distance_measures_to_captured_anchor(world):
    # Anchor at one corner of the plot; a submission near it is close, far corner is far.
    capture_anchor(None, world["unit"], -1.29, 36.80)
    world["unit"].refresh_from_db()
    near = _sub(world, "-1.2901", "36.8001", "near")
    assert near.distance_to_unit_m < 30       # ~metres from the captured anchor
    far = _sub(world, "-1.28", "36.81", "far")  # opposite corner
    assert far.distance_to_unit_m > 1000
