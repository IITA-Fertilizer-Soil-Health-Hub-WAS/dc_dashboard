"""Plot election slice 3: point-in-polygon + farmer-field anchor capture."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.common.geo import point_in_polygon
from apps.fieldwork.anchor import capture_anchor
from apps.fieldwork.election import elect_candidate
from apps.fieldwork.models import CandidatePlot, CollectionUnit
from apps.projects.models import Organization, Project
from apps.rbac.models import Membership, Role

pytestmark = pytest.mark.django_db

# A 0.01°-square around (lat -1.29, lon 36.80). GeoJSON coords are [lon, lat].
SQUARE = {"type": "Polygon", "coordinates": [[
    [36.80, -1.29], [36.81, -1.29], [36.81, -1.28], [36.80, -1.28], [36.80, -1.29]]]}


def test_point_in_polygon_inside_and_outside():
    assert point_in_polygon(-1.285, 36.805, SQUARE) is True   # inside
    assert point_in_polygon(-1.30, 36.805, SQUARE) is False   # south of it
    assert point_in_polygon(-1.285, 36.90, SQUARE) is False   # east of it
    assert point_in_polygon(None, 36.8, SQUARE) is False       # bad input
    assert point_in_polygon(-1.285, 36.805, {}) is False       # no geometry


def test_point_in_polygon_honours_holes():
    donut = {"type": "Polygon", "coordinates": [
        [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],       # exterior
        [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]]}      # hole
    assert point_in_polygon(0.5, 0.5, donut) is True    # in ring, outside hole
    assert point_in_polygon(2, 2, donut) is False       # inside the hole


@pytest.fixture
def elected_unit(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    uc = Project.objects.create(code="PROJ-A", name="A", organization=org)
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True, organization=org)
    Membership.objects.create(user=coord, project=uc, role=Role.TRIAL_COORDINATOR)
    cand = CandidatePlot.objects.create(
        project=uc, trial_key="T1", candidate_ref="A", rank=1, geometry=SQUARE,
        centroid_lat=-1.285, centroid_lon=36.805)
    unit = elect_candidate(coord, cand)
    return {"uc": uc, "coord": coord, "unit": unit}


def test_capture_inside_freezes_anchor(elected_unit):
    unit, coord = elected_unit["unit"], elected_unit["coord"]
    assert unit.anchor_captured is False
    ok, msg = capture_anchor(coord, unit, -1.285, 36.805)
    assert ok
    unit.refresh_from_db()
    assert unit.anchor_captured is True
    assert float(unit.lat) == -1.285 and float(unit.lon) == 36.805
    assert unit.anchor_captured_by == coord and unit.anchor_captured_at is not None


def test_capture_outside_is_rejected(elected_unit):
    unit, coord = elected_unit["unit"], elected_unit["coord"]
    ok, msg = capture_anchor(coord, unit, -1.35, 36.805)  # south of the boundary
    assert not ok and "outside" in msg.lower()
    unit.refresh_from_db()
    assert unit.anchor_captured is False


def test_capture_via_post(client, elected_unit):
    client.force_login(elected_unit["coord"])
    url = reverse("console:plot_elect", args=["PROJ-A", "T1"])
    resp = client.post(url, {"action": "capture_anchor", "lat": "-1.285", "lon": "36.805"})
    assert resp.status_code == 302
    unit = CollectionUnit.objects.get(pk=elected_unit["unit"].pk)
    assert unit.anchor_captured is True


def test_reelection_resets_anchor(elected_unit):
    unit, coord, uc = elected_unit["unit"], elected_unit["coord"], elected_unit["uc"]
    capture_anchor(coord, unit, -1.285, 36.805)
    other = CandidatePlot.objects.create(
        project=uc, trial_key="T1", candidate_ref="B", rank=2, geometry=SQUARE,
        centroid_lat=-1.285, centroid_lon=36.805)
    elect_candidate(coord, other)
    unit.refresh_from_db()
    assert unit.anchor_captured is False  # new elected outline → anchor must be re-captured
