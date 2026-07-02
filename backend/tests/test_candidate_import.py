"""Plot election slice 1: GeoJSON candidate-plot import + centroid."""
from __future__ import annotations

import pytest

from apps.common.geo import polygon_centroid
from apps.fieldwork.candidate_import import import_candidates
from apps.fieldwork.models import CandidatePlot
from apps.usecases.models import Organization, UseCase

pytestmark = pytest.mark.django_db


def _square(lon, lat, d=0.001):
    return {"type": "Polygon", "coordinates": [[
        [lon, lat], [lon + d, lat], [lon + d, lat + d], [lon, lat + d], [lon, lat]]]}


def _fc():
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": _square(36.82, -1.29),
         "properties": {"trial_id": "T1", "candidate_ref": "A", "rank": 1,
                        "accessibility": "easy", "cropping_region": "maize-legume"}},
        {"type": "Feature", "geometry": _square(36.83, -1.30),
         "properties": {"trial_id": "T1", "candidate_ref": "B", "rank": 2,
                        "accessibility": "moderate"}},
        {"type": "Feature", "geometry": _square(36.84, -1.31),
         "properties": {"trial_id": "T1", "candidate_ref": "backup", "rank": 4,
                        "role": "backup"}},
        {"type": "Feature", "geometry": _square(37.00, -1.10),
         "properties": {"trial_id": "T2", "candidate_ref": "A", "rank": 1}},
    ]}


@pytest.fixture
def uc():
    org = Organization.objects.create(code="o", name="O")
    return UseCase.objects.create(code="PROJ-A", name="A", organization=org)


def test_polygon_centroid_of_square():
    lat, lon = polygon_centroid(_square(10.0, 20.0, d=2.0))
    assert abs(lon - 10.8) < 0.01 and abs(lat - 20.8) < 0.01  # mean of 5 ring vertices
    assert polygon_centroid({"type": "Point", "coordinates": [1, 2]}) is None


def test_import_groups_by_trial_and_sets_fields(uc):
    stats = import_candidates(uc, _fc())
    assert stats.created == 4 and stats.updated == 0 and stats.trials == 2
    a = CandidatePlot.objects.get(use_case=uc, trial_key="T1", candidate_ref="A")
    assert a.rank == 1 and a.accessibility == "easy" and a.cropping_region == "maize-legume"
    assert a.role == CandidatePlot.Role.PRIMARY
    assert a.centroid_lat is not None and a.centroid_lon is not None
    assert a.status == CandidatePlot.Status.PROPOSED
    bk = CandidatePlot.objects.get(use_case=uc, trial_key="T1", candidate_ref="backup")
    assert bk.role == CandidatePlot.Role.BACKUP


def test_import_is_idempotent(uc):
    import_candidates(uc, _fc())
    stats = import_candidates(uc, _fc())
    assert stats.created == 0 and stats.updated == 4
    assert CandidatePlot.objects.filter(use_case=uc).count() == 4


def test_bad_features_skipped_not_fatal(uc):
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": _square(1, 1),
         "properties": {"candidate_ref": "A"}},  # no trial key
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 1]},
         "properties": {"trial_id": "T9", "candidate_ref": "A"}},  # not a polygon
        {"type": "Feature", "geometry": _square(2, 2),
         "properties": {"trial_id": "T9", "candidate_ref": "B"}},  # good
    ]}
    stats = import_candidates(uc, fc)
    assert stats.created == 1 and stats.skipped == 2 and len(stats.errors) == 2
    assert CandidatePlot.objects.filter(use_case=uc).count() == 1


def test_custom_trial_prop(uc):
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": _square(1, 1),
         "properties": {"area_ref": "AR1", "candidate_ref": "A"}},
    ]}
    stats = import_candidates(uc, fc, trial_prop="area_ref")
    assert stats.created == 1
    assert CandidatePlot.objects.get(use_case=uc).trial_key == "AR1"
