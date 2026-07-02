"""Field-data integrity: statistical outliers, curbstoning signals (shared GPS,
implausible submission pace), and the per-household season timeline."""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.rbac.models import Role, UseCaseMembership
from apps.submissions.models import Enumerator, Household, Submission, SubmissionValue
from apps.usecases.models import EventScheduleItem, FormDefinition, Organization, UseCase
from apps.validation.engine import run_for_use_case
from apps.validation.models import ValidationFlag, ValidationRule

pytestmark = pytest.mark.django_db


@pytest.fixture
def world():
    org = Organization.objects.create(code="o", name="O")
    uc = UseCase.objects.create(code="PROJ-A", name="A", organization=org)
    form = FormDefinition.objects.create(use_case=uc, ona_form_id=1,
                                         role=FormDefinition.Role.VALIDATION)
    return {"uc": uc, "form": form, "org": org}


def _sub(world, uuid, **kw):
    return Submission.objects.create(
        use_case=world["uc"], form=world["form"], ona_uuid=uuid, content_hash=uuid, **kw)


# --- Statistical outliers ----------------------------------------------------

def test_numeric_outlier_flags_only_the_extreme_value(world):
    uc = world["uc"]
    # 24 tight values around 200 + one wild 940 (inside any generous range, but 4σ+).
    for i in range(24):
        s = _sub(world, f"n{i}")
        SubmissionValue.objects.create(submission=s, field_key="yield", current_value=200 + i % 3)
    wild = _sub(world, "wild")
    SubmissionValue.objects.create(submission=wild, field_key="yield", current_value=940)

    ValidationRule.objects.create(
        use_case=uc, code="yield-outlier",
        rule_type=ValidationRule.RuleType.NUMERIC_OUTLIER, params={"field": "yield"})
    run_for_use_case(uc)

    flags = ValidationFlag.objects.filter(status="OPEN")
    assert flags.count() == 1
    flag = flags.get()
    assert flag.submission_id == wild.id
    assert flag.detail["value"] == 940.0 and abs(flag.detail["z"]) >= 3


def test_numeric_outlier_silent_below_min_n(world):
    uc = world["uc"]
    for i in range(5):  # fewer than min_n=20 → distribution not trusted
        s = _sub(world, f"s{i}")
        SubmissionValue.objects.create(submission=s, field_key="yield", current_value=i * 100)
    ValidationRule.objects.create(
        use_case=uc, code="yo", rule_type=ValidationRule.RuleType.NUMERIC_OUTLIER,
        params={"field": "yield"})
    run_for_use_case(uc)
    assert ValidationFlag.objects.filter(status="OPEN").count() == 0


# --- Curbstoning: shared GPS -------------------------------------------------

def test_geo_duplicate_flags_shared_point_across_households(world):
    uc = world["uc"]
    h1 = Household.objects.create(use_case=uc, hhid="H1")
    h2 = Household.objects.create(use_case=uc, hhid="H2")
    # Two different households at the exact same GPS → never moved.
    _sub(world, "a", household=h1, lat="-1.2900", lon="36.8000")
    _sub(world, "b", household=h2, lat="-1.2900", lon="36.8000")
    # A third household, elsewhere → not flagged.
    h3 = Household.objects.create(use_case=uc, hhid="H3")
    _sub(world, "c", household=h3, lat="-1.5000", lon="36.9000")

    ValidationRule.objects.create(
        use_case=uc, code="dup-gps", rule_type=ValidationRule.RuleType.GEO_DUPLICATE)
    run_for_use_case(uc)

    flagged = set(ValidationFlag.objects.filter(status="OPEN").values_list("submission__ona_uuid", flat=True))
    assert flagged == {"a", "b"}


def test_geo_duplicate_ignores_same_household_revisits(world):
    uc = world["uc"]
    h1 = Household.objects.create(use_case=uc, hhid="H1")
    _sub(world, "e1", household=h1, lat="-1.2900", lon="36.8000")
    _sub(world, "e2", household=h1, lat="-1.2900", lon="36.8000")  # same HH, later event
    ValidationRule.objects.create(
        use_case=uc, code="dup-gps", rule_type=ValidationRule.RuleType.GEO_DUPLICATE)
    run_for_use_case(uc)
    assert ValidationFlag.objects.filter(status="OPEN").count() == 0


# --- Curbstoning: submission speed -------------------------------------------

def test_submission_speed_flags_a_burst(world):
    uc = world["uc"]
    enum = Enumerator.objects.create(use_case=uc, enid="E1")
    base = timezone.now()
    # 8 submissions within ~14 min → exceeds max=6 in a 30-min window.
    for i in range(8):
        _sub(world, f"burst{i}", enumerator=enum,
             ona_submission_time=base + timedelta(minutes=2 * i))
    # A lone, well-separated submission → not part of the burst.
    _sub(world, "calm", enumerator=enum, ona_submission_time=base + timedelta(hours=6))

    ValidationRule.objects.create(
        use_case=uc, code="speed", rule_type=ValidationRule.RuleType.SUBMISSION_SPEED,
        params={"max": 6, "window_min": 30})
    run_for_use_case(uc)

    flagged = set(ValidationFlag.objects.filter(status="OPEN").values_list("submission__ona_uuid", flat=True))
    assert "calm" not in flagged
    assert len([f for f in flagged if f.startswith("burst")]) == 8


# --- Household timeline -------------------------------------------------------

def test_household_timeline_orders_events_and_shows_gaps(client, world, django_user_model):
    uc = world["uc"]
    coord = django_user_model.objects.create_user(
        "c@x.org", "pw", is_active=True, organization=world["org"])
    UseCaseMembership.objects.create(user=coord, use_case=uc, role=Role.TRIAL_COORDINATOR)
    EventScheduleItem.objects.create(use_case=uc, event_key="Event1", sequence=1)
    EventScheduleItem.objects.create(use_case=uc, event_key="Event2", sequence=2)
    hh = Household.objects.create(use_case=uc, hhid="H-42")
    _sub(world, "ev1", household=hh, event_key="Event1", event_date=timezone.localdate())
    # Event2 deliberately missing → a gap in the timeline.

    client.force_login(coord)
    resp = client.get(reverse("dashboards:household_timeline", args=["PROJ-A", hh.id]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "H-42" in body
    assert "Event1" in body and "Event2" in body
    assert "not collected" in body  # the gap is surfaced
