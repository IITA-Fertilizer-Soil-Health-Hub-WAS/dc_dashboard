"""Ingestion engine tests using a fake ONA client (no network).

Proves the config-driven pipeline replaces dataprocessing.R: registration forms
build Enumerators/Households, validation forms build immutable Submissions +
authoritative SubmissionValues, with idempotency and edit-preservation.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from django.conf import settings
from django.utils import timezone

from apps.config_admin.loader import import_config, load_yaml
from apps.ingestion.sync import sync_use_case
from apps.submissions.models import Enumerator, Household, Submission, SubmissionValue
from apps.usecases.models import FormDefinition, UseCase

pytestmark = pytest.mark.django_db


def test_auto_map_on_sync_populates_unmapped_form():
    """A form onboarded with NO field mappings auto-maps from the first record on
    first sync, so submissions + enumerators populate without manual mapping."""
    uc = UseCase.objects.create(code="AM", name="AM")
    FormDefinition.objects.create(use_case=uc, ona_form_id=7,
                                  role=FormDefinition.Role.VALIDATION)  # no mappings

    class Fake:
        def get_data(self, fid):
            return [{"_uuid": "u1", "enumerator_id": "EN1", "hhid": "HH1",
                     "intro/event": "Event1", "crop": "maize"}]

    sync_use_case(uc, client=Fake())
    form = uc.forms.first()
    assert form.mappings.exists()  # auto-created
    targets = set(form.mappings.values_list("target_field", flat=True))
    assert {"ENID", "HHID"} <= targets
    sub = Submission.objects.get(use_case=uc, ona_uuid="u1")
    assert sub.enumerator.enid == "EN1"
    assert sub.household.hhid == "HH1"

SNS_PATH = Path(settings.USECASE_CONFIG_DIR) / "sns-rwanda.yaml"


class FakeOnaClient:
    """Returns canned records per form_id, mimicking the ONA API shape.

    Robust to int/str form ids: sync now passes ``form.server_ref`` (a string),
    just as the real ONA backend coerces with ``int(form_id)``."""

    def __init__(self, by_form: dict[int, list[dict]]):
        self.by_form = by_form

    def get_data(self, form_id) -> list[dict]:
        rows = self.by_form.get(form_id)
        if rows is None:
            try:
                rows = self.by_form.get(int(form_id))
            except (TypeError, ValueError):
                rows = None
        if rows is None:
            rows = self.by_form.get(str(form_id))
        return list(rows or [])


def _records():
    enum_form = 750671
    hh_form = 750672
    val_form = 752552
    geo = "new_barcode_dataSCRIBEcode_02c9e5d2f2504f57ae636de562b9f837_ENDDS/household_geopoint_dataSCRIBEcode_46dd9da06bc541a0a2917f8b4fcf0bd8_ENDDS"
    enid_path = "enumerator_ID_dataSCRIBEcode_a1e28af2b2a745b6bb29467aa015164c_ENDDS"
    hhid_path = "new_barcode_dataSCRIBEcode_02c9e5d2f2504f57ae636de562b9f837_ENDDS/household_ID_dataSCRIBEcode_85e11f6972e14bd0bfc5282a6d6b226f_ENDDS"
    country_path = "country_ID_dataSCRIBEcode_95be8089f5c845e183a371095d44a55e_ENDDS"
    return {
        enum_form: [
            {"purpose/enumerator_ID": "RSENRW000123", "purpose/first_name": "Aline",
             "purpose/surname": "Uwase", "purpose/phone_number": "0788000000", "today": "2026-01-01"},
            {"purpose/enumerator_ID": "RSENRW000001", "purpose/first_name": "Test",
             "purpose/surname": "Account", "today": "2026-01-01"},  # test enumerator
        ],
        hh_form: [
            {enid_path: "RSENRW000123", hhid_path: "RSHHRW000999",
             geo: "-1.95 30.06 1500 5", country_path: "Rwanda", "today": "2026-01-10"},
        ],
        val_form: [
            {"_uuid": "uuid-aaa", "_id": 1, "_submission_time": "2026-01-24T08:00:00",
             "intro/enumerator_ID": "RSENRW000123", "intro/household_ID": "RSHHRW000999",
             "intro/event": "Event1", "intro/country": "Rwanda", "crop": "potatoIrish",
             "intro/latitude": "-1.95", "intro/longitude": "30.06", "today": "2026-01-24"},
            {"_uuid": "uuid-bbb", "_id": 2, "_submission_time": "2026-02-22T08:00:00",
             "intro/enumerator_ID": "RSENRW000123", "intro/household_ID": "RSHHRW000999",
             "intro/event": "Event2", "crop": "potatoIrish", "today": "2026-02-22"},
            # A submission from the test enumerator — must be skipped.
            {"_uuid": "uuid-ccc", "_id": 3, "intro/enumerator_ID": "RSENRW000001",
             "intro/household_ID": "RSHHRW000001", "intro/event": "Event1", "today": "2026-01-24"},
        ],
    }


@pytest.fixture
def use_case():
    return import_config(load_yaml(SNS_PATH))


def test_full_sync_builds_entities(use_case):
    client = FakeOnaClient(_records())
    stats = sync_use_case(use_case, client=client)

    # Enumerators: real one is not test; test one flagged.
    assert Enumerator.objects.filter(use_case=use_case, is_test=False).count() == 1
    assert Enumerator.objects.get(enid="RSENRW000001").is_test is True

    # Household built with geopoint split + country + site-selection date.
    hh = Household.objects.get(hhid="RSHHRW000999")
    assert float(hh.lat) == pytest.approx(-1.95)
    assert hh.country == "Rwanda"
    assert hh.site_selection_date.isoformat() == "2026-01-10"

    # Two real submissions created; the test-enumerator one skipped.
    assert Submission.objects.filter(use_case=use_case).count() == 2
    assert stats.created == 2
    assert stats.skipped_test == 1

    # Crop alias resolved potatoIrish -> potato; FKs linked; event captured.
    s1 = Submission.objects.get(ona_uuid="uuid-aaa")
    assert s1.crop.name == "potato"
    assert s1.event_key == "Event1"
    assert s1.enumerator.enid == "RSENRW000123"
    assert s1.household.hhid == "RSHHRW000999"
    assert s1.event_date.isoformat() == "2026-01-24"

    # Values: raw == current at ingest.
    v = SubmissionValue.objects.get(submission=s1, field_key="event_key")
    assert v.raw_value == v.current_value == "Event1"


def test_idempotent_resync_no_duplicates(use_case):
    client = FakeOnaClient(_records())
    sync_use_case(use_case, client=client)
    stats2 = sync_use_case(use_case, client=client)
    assert Submission.objects.filter(use_case=use_case).count() == 2
    assert stats2.created == 0
    assert stats2.unchanged == 2


def test_reingest_preserves_reviewer_edit(use_case):
    client = FakeOnaClient(_records())
    sync_use_case(use_case, client=client)

    # Simulate a reviewer edit on a value (Phase 5 will do this via the API).
    s1 = Submission.objects.get(ona_uuid="uuid-aaa")
    v = SubmissionValue.objects.get(submission=s1, field_key="event_key")
    v.current_value = "Event1-CORRECTED"
    v.is_edited = True
    v.edited_at = timezone.now()
    v.save()

    # Change the raw record so re-ingest updates raw_value.
    recs = _records()
    recs[752552][0]["intro/country"] = "Rwanda-changed"
    sync_use_case(use_case, client=FakeOnaClient(recs))

    v.refresh_from_db()
    # Edited current_value preserved; raw_value still tracks ONA.
    assert v.current_value == "Event1-CORRECTED"
    assert v.is_edited is True
