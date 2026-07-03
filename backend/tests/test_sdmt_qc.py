"""SDMT-inspired: rejection-reason taxonomy on decline + job QC%/closure + Corrected."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.fieldwork.models import CollectionUnit, Job, UnitAssignment
from apps.fieldwork.services import job_progress
from apps.projects.models import FormDefinition, Organization, Project
from apps.rbac.models import Role, UseCaseMembership
from apps.review.models import RejectionReason, Review, ReviewState
from apps.review.services import decline
from apps.submissions.models import Submission, SubmissionValue

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    uc = Project.objects.create(code="PROJ-A", name="A", organization=org)
    form = FormDefinition.objects.create(project=uc, ona_form_id=1, role=FormDefinition.Role.VALIDATION)
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True, organization=org)
    UseCaseMembership.objects.create(user=coord, project=uc, role=Role.REGIONAL_COORDINATOR)
    UseCaseMembership.objects.create(user=coord, project=uc, role=Role.TRIAL_COORDINATOR)
    return {"uc": uc, "form": form, "coord": coord}


def test_decline_records_rejection_reason(world):
    uc, form, coord = world["uc"], world["form"], world["coord"]
    reason = RejectionReason.objects.create(project=uc, code="too-far", label="Too far from plot")
    sub = Submission.objects.create(project=uc, form=form, ona_uuid="d1", content_hash="h")
    decline(coord, sub, note="off site", reason=reason)
    review = Review.objects.get(submission=sub)
    assert review.state == ReviewState.DECLINED
    assert review.rejection_reason == reason


def test_review_screen_offers_reasons_and_captures(client, world):
    uc, form, coord = world["uc"], world["form"], world["coord"]
    reason = RejectionReason.objects.create(project=uc, code="security", label="Security threat")
    RejectionReason.objects.create(code="global-x", label="Global reason")  # global (no project)
    sub = Submission.objects.create(project=uc, form=form, ona_uuid="d2", content_hash="h")
    client.force_login(coord)
    url = reverse("dashboards:submission_review", args=["PROJ-A", sub.id])
    page = client.get(url).content
    assert b"Security threat" in page and b"Global reason" in page  # project + global reasons
    client.post(url, {"action": "DECLINE", "rejection_reason": str(reason.pk), "note": "unsafe"})
    assert Review.objects.get(submission=sub).rejection_reason == reason


def test_job_progress_qc_and_closure(world, django_user_model):
    uc, form, coord = world["uc"], world["form"], world["coord"]
    job = Job.objects.create(project=uc, name="J1")
    u1 = CollectionUnit.objects.create(project=uc, code="U1")
    u2 = CollectionUnit.objects.create(project=uc, code="U2")
    UnitAssignment.objects.create(job=job, unit=u1)
    UnitAssignment.objects.create(job=job, unit=u2)
    s1 = Submission.objects.create(project=uc, form=form, ona_uuid="s1", content_hash="h", collection_unit=u1)
    Submission.objects.create(project=uc, form=form, ona_uuid="s2", content_hash="h", collection_unit=u2)
    Review.objects.filter(submission=s1).update(state=ReviewState.APPROVED)
    p = job_progress(job)
    assert p["submissions"] == 2 and p["approved_submissions"] == 1
    assert p["qc_pct"] == 50
    # Closure
    job.close(coord, note="done")
    job.refresh_from_db()
    assert job.status == Job.Status.CLOSED and job.closed_by == coord and job.closure_note == "done"


def test_submission_is_corrected(world):
    uc, form = world["uc"], world["form"]
    sub = Submission.objects.create(project=uc, form=form, ona_uuid="c1", content_hash="h")
    assert sub.is_corrected is False
    SubmissionValue.objects.create(submission=sub, field_key="x", raw_value="1",
                                   current_value="2", is_edited=True)
    assert Submission.objects.get(pk=sub.pk).is_corrected is True
