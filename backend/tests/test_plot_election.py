"""Plot election slice 2: election service + coordinator election screens."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.fieldwork.election import elect_candidate, election_progress, trial_rows
from apps.fieldwork.models import CandidatePlot, CollectionUnit
from apps.projects.models import Organization, Project
from apps.rbac.models import Membership, Role

pytestmark = pytest.mark.django_db


def _poly(lon, lat, d=0.001):
    return {"type": "Polygon", "coordinates": [[
        [lon, lat], [lon + d, lat], [lon + d, lat + d], [lon, lat + d], [lon, lat]]]}


@pytest.fixture
def world(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    uc = Project.objects.create(code="PROJ-A", name="A", organization=org)
    mk = lambda ref, rank, role="PRIMARY": CandidatePlot.objects.create(  # noqa: E731
        project=uc, trial_key="T1", candidate_ref=ref, rank=rank, role=role,
        geometry=_poly(36.8 + rank / 100, -1.29), centroid_lat=-1.29,
        centroid_lon=36.8 + rank / 100, accessibility="easy")
    a, b, bk = mk("A", 1), mk("B", 2), mk("BK", 4, role="BACKUP")
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True, organization=org)
    Membership.objects.create(user=coord, project=uc, role=Role.REGIONAL_COORDINATOR)
    Membership.objects.create(user=coord, project=uc, role=Role.TRIAL_COORDINATOR)
    return {"uc": uc, "a": a, "b": b, "bk": bk, "coord": coord}


def test_trial_rows_and_progress(world):
    rows = trial_rows(world["uc"])
    assert len(rows) == 1 and rows[0].count == 3 and rows[0].status == "pending"
    p = election_progress(world["uc"])
    assert p == {"trials": 1, "elected": 0, "pending": 1}


def test_elect_promotes_to_unit_and_marks_siblings(world):
    unit = elect_candidate(world["coord"], world["a"], note="")
    assert isinstance(unit, CollectionUnit) and unit.code == "T1"
    assert unit.attributes["elected_candidate"] == "A"
    assert unit.boundary["type"] == "Polygon"
    world["a"].refresh_from_db()
    world["b"].refresh_from_db()
    assert world["a"].status == CandidatePlot.Status.ELECTED
    assert world["a"].collection_unit_id == unit.id and world["a"].elected_by == world["coord"]
    assert world["b"].status == CandidatePlot.Status.NOT_SELECTED
    assert world["b"].collection_unit_id is None


def test_reelection_reuses_one_unit(world):
    elect_candidate(world["coord"], world["a"])
    elect_candidate(world["coord"], world["b"])
    assert CollectionUnit.objects.filter(project=world["uc"], code="T1").count() == 1
    world["a"].refresh_from_db()
    assert world["a"].status == CandidatePlot.Status.NOT_SELECTED
    unit = CollectionUnit.objects.get(project=world["uc"], code="T1")
    assert unit.attributes["elected_candidate"] == "B"


def test_queue_and_elect_screen(client, world):
    client.force_login(world["coord"])
    q = client.get(reverse("console:plot_election") + "?project=PROJ-A")
    assert q.status_code == 200 and b"T1" in q.content
    screen = client.get(reverse("console:plot_elect", args=["PROJ-A", "T1"]))
    assert screen.status_code == 200 and b"Plot A" in screen.content


def test_elect_via_post(client, world):
    client.force_login(world["coord"])
    url = reverse("console:plot_elect", args=["PROJ-A", "T1"])
    resp = client.post(url, {"action": "elect", "candidate": str(world["a"].pk)})
    assert resp.status_code == 302
    world["a"].refresh_from_db()
    assert world["a"].status == CandidatePlot.Status.ELECTED


def test_backup_requires_reason(client, world):
    client.force_login(world["coord"])
    url = reverse("console:plot_elect", args=["PROJ-A", "T1"])
    client.post(url, {"action": "elect", "candidate": str(world["bk"].pk)})  # no note
    world["bk"].refresh_from_db()
    assert world["bk"].status == CandidatePlot.Status.PROPOSED  # rejected, not elected
    client.post(url, {"action": "elect", "candidate": str(world["bk"].pk), "note": "primaries flooded"})
    world["bk"].refresh_from_db()
    assert world["bk"].status == CandidatePlot.Status.ELECTED


def test_non_coordinator_denied(client, world, django_user_model):
    outsider = django_user_model.objects.create_user("o@x.org", "pw", is_active=True,
                                                     organization=world["uc"].organization)
    client.force_login(outsider)
    resp = client.get(reverse("console:plot_election"))
    assert resp.status_code in (302, 403)
