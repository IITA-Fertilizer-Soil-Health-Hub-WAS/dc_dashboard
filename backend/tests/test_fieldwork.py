"""Feature B, Stage B1: collection units + jobs; submissions matched at ingest."""
from __future__ import annotations

import pytest

from apps.fieldwork.models import CollectionUnit, Job, UnitAssignment
from apps.ingestion.sync import sync_use_case
from apps.submissions.models import Submission
from apps.usecases.models import FieldMapping, FormDefinition, UseCase

pytestmark = pytest.mark.django_db


def test_use_case_unit_type_default():
    uc = UseCase.objects.create(code="UC", name="UC")
    assert uc.unit_type == UseCase.UnitType.FARMER_HOUSEHOLD
    plots = UseCase.objects.create(code="PLOTS", name="Plots",
                                   unit_type=UseCase.UnitType.PLOT)
    assert plots.unit_type == "PLOT"


def test_collection_unit_unique_per_use_case():
    uc = UseCase.objects.create(code="UC", name="UC")
    CollectionUnit.objects.create(use_case=uc, code="HH1")
    from django.db import IntegrityError
    with pytest.raises(IntegrityError):
        CollectionUnit.objects.create(use_case=uc, code="HH1")


def test_job_with_assignments(django_user_model):
    uc = UseCase.objects.create(code="UC", name="UC")
    form = FormDefinition.objects.create(use_case=uc, ona_form_id=1,
                                         role=FormDefinition.Role.VALIDATION)
    unit = CollectionUnit.objects.create(use_case=uc, code="HH1")
    en = django_user_model.objects.create_user("en@x.org", "pw", is_active=True)
    job = Job.objects.create(use_case=uc, name="Round 1", form=form, target_count=10)
    job.assigned_to.add(en)
    UnitAssignment.objects.create(job=job, unit=unit, enumerator=en)

    assert job.assignments.count() == 1
    assert list(job.units.all()) == [unit]
    assert en in job.assigned_to.all()


def _form_with_mappings(uc):
    form = FormDefinition.objects.create(use_case=uc, ona_form_id=9,
                                         role=FormDefinition.Role.VALIDATION)
    for order, (t, s) in enumerate([("ENID", "enid"), ("HHID", "hhid"), ("event_key", "ev")]):
        FieldMapping.objects.create(form=form, target_field=t, source_paths=[s], order=order)
    return form


def test_submission_matched_to_planned_unit(django_user_model):
    uc = UseCase.objects.create(code="UC", name="UC")
    unit = CollectionUnit.objects.create(use_case=uc, code="HH1")
    _form_with_mappings(uc)

    class Fake:
        def get_data(self, fid):
            return [{"_uuid": "u1", "enid": "EN1", "hhid": "HH1", "ev": "Event1"}]

    sync_use_case(uc, client=Fake())
    sub = Submission.objects.get(use_case=uc, ona_uuid="u1")
    assert sub.collection_unit == unit  # matched by HHID -> unit code


def test_submission_creates_its_unit_when_none_planned(django_user_model):
    # Household→unit merge: a submission whose id has no pre-planned unit now
    # creates one on the fly (a unit IS the household/farm/plot).
    uc = UseCase.objects.create(code="UC", name="UC")
    _form_with_mappings(uc)

    class Fake:
        def get_data(self, fid):
            return [{"_uuid": "u2", "enid": "EN1", "hhid": "HH-NEW", "ev": "Event1"}]

    sync_use_case(uc, client=Fake())
    sub = Submission.objects.get(use_case=uc, ona_uuid="u2")
    assert sub.collection_unit is not None
    assert sub.collection_unit.code == "HH-NEW" and sub.collection_unit.use_case == uc


def test_upsert_unit_mirrors_household_and_guards_anchor():
    from apps.ingestion.sync import _upsert_collection_unit

    uc = UseCase.objects.create(code="UC", name="UC")
    # A household-style unit: registration fields are mirrored onto the unit.
    _upsert_collection_unit(uc, {"HHID": "H1", "LAT": "-1.29", "LON": "36.80",
                                 "today": "2026-03-01"})
    u = CollectionUnit.objects.get(use_case=uc, code="H1")
    assert float(u.lat) == -1.29 and str(u.site_selection_date) == "2026-03-01"

    # An elected unit with a captured anchor: its coordinates must NOT be stomped,
    # but non-geo fields are still enriched.
    e = CollectionUnit.objects.create(use_case=uc, code="H2", lat="-1.0", lon="36.0",
                                      anchor_captured=True)
    _upsert_collection_unit(uc, {"HHID": "H2", "LAT": "-9.9", "LON": "9.9",
                                 "today": "2026-04-01"})
    e.refresh_from_db()
    assert float(e.lat) == -1.0  # frozen anchor preserved
    assert str(e.site_selection_date) == "2026-04-01"


def test_unit_match_scoped_to_use_case(django_user_model):
    """A submission gets its OWN project's unit, never another project's."""
    a = UseCase.objects.create(code="A", name="A")
    b = UseCase.objects.create(code="B", name="B")
    b_unit = CollectionUnit.objects.create(use_case=b, code="HH1")  # belongs to B
    _form_with_mappings(a)

    class Fake:
        def get_data(self, fid):
            return [{"_uuid": "x", "enid": "EN1", "hhid": "HH1", "ev": "E1"}]

    sync_use_case(a, client=Fake())
    sub = Submission.objects.get(use_case=a, ona_uuid="x")
    assert sub.collection_unit is not None
    assert sub.collection_unit != b_unit and sub.collection_unit.use_case == a
