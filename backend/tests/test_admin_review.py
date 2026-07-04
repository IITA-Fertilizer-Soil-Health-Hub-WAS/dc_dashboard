"""Review and its audit log are project concerns, not Django-admin models.

They were removed from /admin/ (belong to the project) and surface on-screen at
the project level via the Review tab + Review log page.
"""
from __future__ import annotations

import pytest
from django.contrib import admin as django_admin
from django.urls import NoReverseMatch, reverse

from apps.projects.models import FormDefinition, Organization, Project
from apps.rbac.models import Membership, Role
from apps.review import services
from apps.review.models import Review, ReviewActionLog
from apps.submissions.models import Submission

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    admin = django_user_model.objects.create_superuser("a@x.org", "pw")
    uc = Project.objects.create(code="UC", name="UC", organization=org)
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True, organization=org)
    Membership.objects.create(user=coord, project=uc, role=Role.TRIAL_COORDINATOR)
    form = FormDefinition.objects.create(project=uc, ona_form_id=1,
                                         role=FormDefinition.Role.VALIDATION)
    sub = Submission.objects.create(project=uc, form=form, ona_uuid="u1", content_hash="h")
    services.endorse(admin, sub)
    services.qc_approve(admin, sub)
    return {"admin": admin, "coord": coord, "uc": uc}


def test_review_models_not_registered_in_admin():
    assert Review not in django_admin.site._registry
    assert ReviewActionLog not in django_admin.site._registry
    with pytest.raises(NoReverseMatch):
        reverse("admin:review_review_changelist")


def test_project_review_log_renders(client, world):
    client.force_login(world["coord"])
    resp = client.get(reverse("dashboards:review_log", args=[world["uc"].code]))
    assert resp.status_code == 200
    assert b"Review log" in resp.content
    # The audit actions generated in the fixture are listed.
    assert b"ENDORSE" in resp.content and b"QC_APPROVE" in resp.content


def test_review_log_scoped_to_project(client, django_user_model, world):
    """A coordinator can't read another project's review log."""
    other = Project.objects.create(code="OTHER", name="Other")
    client.force_login(world["coord"])
    resp = client.get(reverse("dashboards:review_log", args=[other.code]))
    assert resp.status_code in (403, 404)


def test_review_tab_links_to_review_log(client, world):
    from apps.review.models import ReviewState
    # Give the coordinator something to see and confirm the tab exposes the link.
    client.force_login(world["coord"])
    html = client.get(reverse("dashboards:tab_review", args=[world["uc"].code])).content
    assert reverse("dashboards:review_log", args=[world["uc"].code]).encode() in html
    assert ReviewState  # imported to keep parity with other review tests
