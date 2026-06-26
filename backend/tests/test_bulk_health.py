"""Bulk review actions + per-use-case review/write-back health on Summary."""
from __future__ import annotations

import pytest

from apps.dashboards.views import _health_counts
from apps.rbac.models import Role, UseCaseMembership
from apps.review import services
from apps.review.models import ReviewState
from apps.submissions.models import Submission
from apps.usecases.models import FormDefinition, UseCase

pytestmark = pytest.mark.django_db


@pytest.fixture
def uc():
    return UseCase.objects.create(code="UC", name="UC")


@pytest.fixture
def form(uc):
    return FormDefinition.objects.create(use_case=uc, ona_form_id=1,
                                         role=FormDefinition.Role.VALIDATION)


def _sub(uc, form, n):
    return Submission.objects.create(use_case=uc, form=form, ona_uuid=f"u{n}", content_hash="h")


@pytest.fixture
def qc(django_user_model, uc):
    user = django_user_model.objects.create_user("qc@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=user, use_case=uc, role=Role.QUALITY_CHECK)
    return user


@pytest.fixture
def coordinator(django_user_model, uc):
    user = django_user_model.objects.create_user("c@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=user, use_case=uc, role=Role.TRIAL_COORDINATOR)
    return user


def test_bulk_qc_approve_many(client, qc, uc, form):
    subs = [_sub(uc, form, i) for i in range(3)]
    client.force_login(qc)
    resp = client.post(f"/usecase/{uc.code}/bulk-action/",
                       {"action": "QC_APPROVE", "ids": [str(s.pk) for s in subs]})
    assert resp.status_code == 200
    for s in subs:
        s.refresh_from_db()
        assert s.review.state == ReviewState.APPROVED


def test_bulk_action_requires_permission(client, django_user_model, uc, form):
    # A viewer has no review permission — bulk QC-approve must change nothing.
    viewer = django_user_model.objects.create_user("v@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=viewer, use_case=uc, role=Role.VIEWER)
    sub = _sub(uc, form, 1)
    client.force_login(viewer)
    resp = client.post(f"/usecase/{uc.code}/bulk-action/",
                       {"action": "QC_APPROVE", "ids": [str(sub.pk)]})
    assert resp.status_code in (200, 403)
    sub.refresh_from_db()
    assert sub.review.state != ReviewState.APPROVED


def test_bulk_decline_many(client, coordinator, uc, form):
    subs = [_sub(uc, form, i) for i in range(2)]
    client.force_login(coordinator)
    client.post(f"/usecase/{uc.code}/bulk-action/",
                {"action": "DECLINE", "ids": [str(s.pk) for s in subs]})
    for s in subs:
        s.refresh_from_db()
        assert s.review.state == ReviewState.DECLINED


def test_health_counts(qc, uc, form):
    a = _sub(uc, form, 1)
    _sub(uc, form, 2)
    _sub(uc, form, 3)
    services.qc_approve(qc, a)
    health = _health_counts(uc)
    assert health["approved"] == 1
    assert health["in_review"] == 2  # the other two are not closed
