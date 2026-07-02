"""Three SDMT features: enumerator quality scorecard, coverage-by-area heatmap,
and the dedicated agronomist QC sign-off queue (Gate 2)."""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.fieldwork.models import CollectionUnit
from apps.kpi.metrics import coverage_metrics, enumerator_metrics
from apps.rbac.models import Role, UseCaseMembership
from apps.review.models import ReviewState
from apps.review.services import endorse
from apps.submissions.models import Enumerator, Submission
from apps.usecases.models import FormDefinition, Organization, UseCase

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    uc = UseCase.objects.create(code="PROJ-A", name="A", organization=org)
    form = FormDefinition.objects.create(use_case=uc, ona_form_id=1,
                                         role=FormDefinition.Role.VALIDATION)
    return {"uc": uc, "form": form, "org": org}


# --- Feature 1: enumerator scorecard -----------------------------------------

def test_scorecard_computes_reject_ontime_gps_and_ranks_by_quality(world):
    uc, form = world["uc"], world["form"]
    unit = CollectionUnit.objects.create(use_case=uc, code="U1", lat="-1.29", lon="36.80")
    good = Enumerator.objects.create(use_case=uc, enid="E-GOOD")
    poor = Enumerator.objects.create(use_case=uc, enid="E-POOR")
    today = timezone.now()

    # Good enumerator: approved, on-time, on the plot.
    s = Submission.objects.create(
        use_case=uc, form=form, ona_uuid="g1", content_hash="g1", enumerator=good,
        collection_unit=unit, lat="-1.29", lon="36.80",
        event_date=today.date(), ona_submission_time=today)
    s.review.state = ReviewState.APPROVED
    s.review.save(update_fields=["state"])

    # Poor enumerator: declined, late (10-day lag), ~1.5 km off the plot.
    ev = today.date() - timedelta(days=10)
    s2 = Submission.objects.create(
        use_case=uc, form=form, ona_uuid="p1", content_hash="p1", enumerator=poor,
        collection_unit=unit, lat="-1.30", lon="36.81",
        event_date=ev, ona_submission_time=today)
    s2.review.state = ReviewState.DECLINED
    s2.review.save(update_fields=["state"])

    m = enumerator_metrics(uc, "all")
    by_enid = {r["enumerator__enid"]: r for r in m["leaderboard"]}
    assert by_enid["E-GOOD"]["approval_pct"] == 100
    assert by_enid["E-GOOD"]["on_time_pct"] == 100
    assert by_enid["E-GOOD"]["gps_err_m"] == 0
    assert by_enid["E-POOR"]["reject_pct"] == 100
    assert by_enid["E-POOR"]["on_time_pct"] == 0
    assert by_enid["E-POOR"]["gps_err_m"] > 500
    # Ranked by composite quality → the good enumerator is first.
    assert m["leaderboard"][0]["enumerator__enid"] == "E-GOOD"
    assert by_enid["E-GOOD"]["quality_score"] > by_enid["E-POOR"]["quality_score"]


# --- Feature 2: coverage-by-area heatmap -------------------------------------

def test_coverage_by_area_buckets_and_orders_behindmost_first(world):
    uc, form = world["uc"], world["form"]
    # Musanze: 2 units, 2 collected (100%). Burera: 2 units, 0 collected (0%).
    for i in range(2):
        u = CollectionUnit.objects.create(use_case=uc, code=f"M{i}", district="Musanze")
        Submission.objects.create(use_case=uc, form=form, ona_uuid=f"m{i}",
                                  content_hash=f"m{i}", collection_unit=u)
    for i in range(2):
        CollectionUnit.objects.create(use_case=uc, code=f"B{i}", district="Burera")

    areas = coverage_metrics(uc)["areas"]
    by_area = {a["area"]: a for a in areas}
    assert by_area["Musanze"]["pct"] == 100 and by_area["Musanze"]["collected"] == 2
    assert by_area["Burera"]["pct"] == 0 and by_area["Burera"]["pending"] == 2
    assert areas[0]["area"] == "Burera"  # behind-most first


# --- Feature 3: agronomist QC sign-off queue ---------------------------------

@pytest.fixture
def endorser(world, django_user_model):
    user = django_user_model.objects.create_user(
        "c@x.org", "pw", is_active=True, organization=world["org"])
    UseCaseMembership.objects.create(user=user, use_case=world["uc"], role=Role.TRIAL_COORDINATOR)
    return user


@pytest.fixture
def validator(world, django_user_model):
    user = django_user_model.objects.create_user(
        "v@x.org", "pw", is_active=True, organization=world["org"])
    UseCaseMembership.objects.create(user=user, use_case=world["uc"], role=Role.REGIONAL_COORDINATOR)
    return user


def _pending_sub(world, endorser, uuid):
    sub = Submission.objects.create(
        use_case=world["uc"], form=world["form"], ona_uuid=uuid, content_hash=uuid)
    endorse(endorser, sub)  # Gate 1 → QC_PENDING
    return sub


def test_qc_queue_lists_only_qc_pending(client, world, endorser, validator):
    _pending_sub(world, endorser, "PENDING01")
    Submission.objects.create(use_case=world["uc"], form=world["form"],
                              ona_uuid="INGESTED9", content_hash="INGESTED9")  # still INGESTED
    client.force_login(validator)
    resp = client.get(reverse("dashboards:qc_signoff", args=["PROJ-A"]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "PENDING0" in body            # QC_PENDING one shown
    assert "INGESTED" not in body        # INGESTED one not in the Gate-2 queue


def test_qc_validate_approves(client, world, endorser, validator):
    # Two-person rule: a different user validates than the one who endorsed.
    sub = _pending_sub(world, endorser, "q2")
    client.force_login(validator)
    resp = client.post(reverse("dashboards:qc_signoff", args=["PROJ-A"]),
                       {"submission": str(sub.id), "action": "QC_APPROVE", "note": ""})
    assert resp.status_code == 302
    sub.review.refresh_from_db()
    assert sub.review.state == ReviewState.APPROVED


def test_qc_queue_forbidden_without_validator_right(client, world, django_user_model):
    plain = django_user_model.objects.create_user(
        "p@x.org", "pw", is_active=True, organization=world["org"])
    UseCaseMembership.objects.create(user=plain, use_case=world["uc"], role=Role.ENUMERATOR)
    client.force_login(plain)
    resp = client.get(reverse("dashboards:qc_signoff", args=["PROJ-A"]))
    assert resp.status_code == 404
