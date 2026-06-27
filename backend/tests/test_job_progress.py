"""Feature B, Stage B4: expected-vs-actual completion roll-ups."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from apps.fieldwork.models import CollectionUnit, Job, UnitAssignment
from apps.fieldwork.services import (
    job_enumerator_progress,
    job_progress,
    use_case_jobs_progress,
)
from apps.submissions.models import Submission
from apps.usecases.models import FormDefinition, UseCase

pytestmark = pytest.mark.django_db


@pytest.fixture
def job(django_user_model):
    uc = UseCase.objects.create(code="UC", name="UC")
    form = FormDefinition.objects.create(use_case=uc, ona_form_id=1,
                                         role=FormDefinition.Role.VALIDATION)
    job = Job.objects.create(use_case=uc, name="Round 1", form=form, target_count=4)
    units = [CollectionUnit.objects.create(use_case=uc, code=f"HH{i}") for i in range(4)]
    en = django_user_model.objects.create_user("en@x.org", "pw", full_name="Enid",
                                               is_active=True)
    for u in units:
        UnitAssignment.objects.create(job=job, unit=u, enumerator=en)
    # Two of the four units have a matched submission.
    for i in (0, 1):
        Submission.objects.create(use_case=uc, form=form, ona_uuid=f"s{i}",
                                  content_hash="h", collection_unit=units[i])
    return job, uc, units, en, form


def test_job_progress_counts(job):
    j, *_ = job
    p = job_progress(j)
    assert p["total"] == 4
    assert p["collected"] == 2
    assert p["pending"] == 2
    assert p["target"] == 4
    assert p["pct"] == 50
    assert p["overdue"] is False


def test_collected_counts_unit_once_with_multiple_submissions(job):
    j, uc, units, en, form = job
    # A second submission on an already-collected unit must not double-count.
    Submission.objects.create(use_case=uc, form=form, ona_uuid="dup",
                              content_hash="h", collection_unit=units[0])
    assert job_progress(j)["collected"] == 2


def test_overdue_when_deadline_passed_and_incomplete(job):
    j, *_ = job
    j.deadline = date.today() - timedelta(days=1)
    j.save()
    assert job_progress(j)["overdue"] is True


def test_not_overdue_when_complete(job):
    j, uc, units, en, form = job
    for i in (2, 3):  # collect the remaining two
        Submission.objects.create(use_case=uc, form=form, ona_uuid=f"more{i}",
                                  content_hash="h", collection_unit=units[i])
    j.deadline = date.today() - timedelta(days=1)
    j.save()
    p = job_progress(j)
    assert p["collected"] == 4 and p["overdue"] is False


def test_enumerator_progress(job):
    j, *_ = job
    rows = job_enumerator_progress(j)
    assert len(rows) == 1
    assert rows[0]["name"] == "Enid"
    assert rows[0]["collected"] == 2 and rows[0]["total"] == 4 and rows[0]["pct"] == 50


def test_use_case_jobs_progress_excludes_closed(job):
    j, uc, *_ = job
    Job.objects.create(use_case=uc, name="Closed one", status=Job.Status.CLOSED)
    progress = use_case_jobs_progress(uc)
    names = {jp["job"].name for jp in progress}
    assert "Round 1" in names
    assert "Closed one" not in names
