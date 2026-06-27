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


def test_submission_with_no_planned_unit_is_unmatched(django_user_model):
    uc = UseCase.objects.create(code="UC", name="UC")  # no units planned
    _form_with_mappings(uc)

    class Fake:
        def get_data(self, fid):
            return [{"_uuid": "u2", "enid": "EN1", "hhid": "HH-UNKNOWN", "ev": "Event1"}]

    sync_use_case(uc, client=Fake())
    sub = Submission.objects.get(use_case=uc, ona_uuid="u2")
    assert sub.collection_unit is None


def test_unit_match_scoped_to_use_case(django_user_model):
    """A unit code in one project never matches another project's submission."""
    a = UseCase.objects.create(code="A", name="A")
    b = UseCase.objects.create(code="B", name="B")
    CollectionUnit.objects.create(use_case=b, code="HH1")  # belongs to B
    _form_with_mappings(a)

    class Fake:
        def get_data(self, fid):
            return [{"_uuid": "x", "enid": "EN1", "hhid": "HH1", "ev": "E1"}]

    sync_use_case(a, client=Fake())
    sub = Submission.objects.get(use_case=a, ona_uuid="x")
    assert sub.collection_unit is None  # B's HH1 must not match A
