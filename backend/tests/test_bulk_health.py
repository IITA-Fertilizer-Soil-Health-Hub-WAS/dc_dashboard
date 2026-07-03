"""Bulk review actions + per-use-case review/write-back health on Summary."""
from __future__ import annotations

import pytest

from apps.dashboards.views import _health_counts
from apps.rbac.models import Role, UseCaseMembership
from apps.review import services
from apps.review.models import ReviewState
from apps.submissions.models import Submission
from apps.usecases.models import FormDefinition, Project

pytestmark = pytest.mark.django_db


@pytest.fixture
def uc():
    return Project.objects.create(code="UC", name="UC")


@pytest.fixture
def form(uc):
    return FormDefinition.objects.create(project=uc, ona_form_id=1,
                                         role=FormDefinition.Role.VALIDATION)


def _sub(uc, form, n):
    return Submission.objects.create(project=uc, form=form, ona_uuid=f"u{n}", content_hash="h")


@pytest.fixture
def qc(django_user_model, uc):
    # Coordinators are the reviewers; they can QC-approve.
    user = django_user_model.objects.create_user("qc@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=user, project=uc, role=Role.COUNTRY_COORDINATOR)
    return user


@pytest.fixture
def coordinator(django_user_model, uc):
    user = django_user_model.objects.create_user("c@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=user, project=uc, role=Role.TRIAL_COORDINATOR)
    return user


@pytest.fixture
def regional(django_user_model, uc):
    user = django_user_model.objects.create_user("r@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=user, project=uc, role=Role.REGIONAL_COORDINATOR)
    return user


def test_bulk_endorse_then_validate(client, qc, regional, uc, form):
    subs = [_sub(uc, form, i) for i in range(3)]
    # Gate 1: a Country Coordinator bulk-endorses.
    client.force_login(qc)
    client.post(f"/project/{uc.code}/bulk-action/",
                {"action": "ENDORSE", "ids": [str(s.pk) for s in subs]})
    for s in subs:
        s.refresh_from_db()
        assert s.review.state == ReviewState.QC_PENDING
    # Gate 2: the Regional Coordinator bulk-validates.
    client.force_login(regional)
    resp = client.post(f"/project/{uc.code}/bulk-action/",
                       {"action": "QC_APPROVE", "ids": [str(s.pk) for s in subs]})
    assert resp.status_code == 200
    for s in subs:
        s.refresh_from_db()
        assert s.review.state == ReviewState.APPROVED


def test_gate1_cannot_bulk_validate(client, qc, uc, form):
    # A Country Coordinator endorses but cannot give final validation.
    subs = [_sub(uc, form, i) for i in range(2)]
    client.force_login(qc)
    client.post(f"/project/{uc.code}/bulk-action/",
                {"action": "ENDORSE", "ids": [str(s.pk) for s in subs]})
    client.post(f"/project/{uc.code}/bulk-action/",
                {"action": "QC_APPROVE", "ids": [str(s.pk) for s in subs]})
    for s in subs:
        s.refresh_from_db()
        assert s.review.state == ReviewState.QC_PENDING  # not approved


def test_bulk_action_requires_permission(client, django_user_model, uc, form):
    # A viewer has no review permission — bulk QC-approve must change nothing.
    viewer = django_user_model.objects.create_user("v@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=viewer, project=uc, role=Role.VIEWER)
    sub = _sub(uc, form, 1)
    client.force_login(viewer)
    resp = client.post(f"/project/{uc.code}/bulk-action/",
                       {"action": "QC_APPROVE", "ids": [str(sub.pk)]})
    assert resp.status_code in (200, 403)
    sub.refresh_from_db()
    assert sub.review.state != ReviewState.APPROVED


def test_bulk_decline_many(client, coordinator, uc, form):
    subs = [_sub(uc, form, i) for i in range(2)]
    client.force_login(coordinator)
    client.post(f"/project/{uc.code}/bulk-action/",
                {"action": "DECLINE", "ids": [str(s.pk) for s in subs]})
    for s in subs:
        s.refresh_from_db()
        assert s.review.state == ReviewState.DECLINED


def test_health_counts(qc, regional, uc, form):
    a = _sub(uc, form, 1)
    _sub(uc, form, 2)
    _sub(uc, form, 3)
    services.endorse(qc, a)          # Gate 1
    services.qc_approve(regional, a)  # Gate 2
    health = _health_counts(uc)
    assert health["approved"] == 1
    assert health["in_review"] == 2  # the other two are not closed
