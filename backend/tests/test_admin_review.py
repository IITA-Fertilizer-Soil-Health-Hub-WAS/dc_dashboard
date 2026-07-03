"""The Django-admin Review change page must render (regression: a ReviewActionLog
inline was wrongly attached to Review, which has no FK from the log)."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.projects.models import FormDefinition, Project
from apps.review import services
from apps.review.models import Review
from apps.submissions.models import Submission

pytestmark = pytest.mark.django_db


@pytest.fixture
def review(django_user_model):
    admin = django_user_model.objects.create_superuser("a@x.org", "pw")
    uc = Project.objects.create(code="UC", name="UC")
    form = FormDefinition.objects.create(project=uc, ona_form_id=1,
                                         role=FormDefinition.Role.VALIDATION)
    sub = Submission.objects.create(project=uc, form=form, ona_uuid="u1", content_hash="h")
    # Generate a couple of audit actions so the trail renders.
    services.endorse(admin, sub)
    services.qc_approve(admin, sub)
    return admin, Review.objects.get(submission=sub)


def test_admin_review_change_page_renders(client, review):
    admin, rev = review
    client.force_login(admin)
    url = reverse("admin:review_review_change", args=[rev.pk])
    resp = client.get(url)
    assert resp.status_code == 200
    assert b"Audit trail" in resp.content
    assert b"ENDORSE" in resp.content and b"QC_APPROVE" in resp.content


def test_admin_review_changelist_renders(client, review):
    admin, _ = review
    client.force_login(admin)
    resp = client.get(reverse("admin:review_review_changelist"))
    assert resp.status_code == 200
