"""collected_by surfaces in the dashboards: ranking, data preview, and exports."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.ingestion.sync import sync_use_case
from apps.rbac.models import Role, UseCaseMembership
from apps.review.models import Review, ReviewAction, ReviewActionLog, ReviewState
from apps.submissions.models import Enumerator, Submission
from apps.usecases.models import FieldMapping, FormDefinition, UseCase

pytestmark = pytest.mark.django_db


@pytest.fixture
def attributed(django_user_model):
    """A use case with one submission collected by a linked account, approved."""
    collector = django_user_model.objects.create_user(
        "collector@x.org", "pw", full_name="Field Collector", is_active=True
    )
    uc = UseCase.objects.create(code="ATTR", name="Attribution UC")
    Enumerator.objects.create(use_case=uc, enid="EN1", user=collector)
    form = FormDefinition.objects.create(
        use_case=uc, ona_form_id=1, role=FormDefinition.Role.VALIDATION
    )
    for order, (t, s) in enumerate([("ENID", "enid"), ("HHID", "hhid"), ("event_key", "ev")]):
        FieldMapping.objects.create(form=form, target_field=t, source_paths=[s], order=order)

    class Fake:
        def get_data(self, fid):
            return [{"_uuid": "u1", "enid": "EN1", "hhid": "HH1", "ev": "Event1"}]

    sync_use_case(uc, client=Fake())
    sub = Submission.objects.get(use_case=uc, ona_uuid="u1")
    assert sub.collected_by == collector  # bridge populated it

    Review.objects.update_or_create(
        submission=sub, defaults={"state": ReviewState.APPROVED}
    )
    ReviewActionLog.objects.create(
        submission=sub, action=ReviewAction.QC_APPROVE,
        from_state=ReviewState.QC_PENDING, to_state=ReviewState.APPROVED,
    )

    coord = django_user_model.objects.create_user("co@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=coord, use_case=uc, role=Role.TRIAL_COORDINATOR)
    return uc, collector, coord


def test_ranking_shows_linked_account(client, attributed):
    uc, collector, coord = attributed
    client.force_login(coord)
    resp = client.get(reverse("dashboards:tab_enumerators", args=[uc.code]))
    assert resp.status_code == 200
    assert collector.user_id.encode() in resp.content


def test_data_preview_shows_collected_by(client, attributed):
    uc, collector, coord = attributed
    client.force_login(coord)
    resp = client.get(reverse("dashboards:tab_data", args=[uc.code]))
    assert resp.status_code == 200
    assert b"Collected by" in resp.content
    assert collector.user_id.encode() in resp.content


def test_final_export_includes_collected_by(client, attributed):
    uc, collector, coord = attributed
    client.force_login(coord)
    resp = client.get(reverse("dashboards:export_final", args=[uc.code]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "collected_by" in body.splitlines()[0]  # header
    assert collector.user_id in body


def test_audit_export_includes_collector(client, attributed):
    uc, collector, coord = attributed
    client.force_login(coord)
    resp = client.get(reverse("dashboards:export_audit", args=[uc.code]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "collected_by" in body.splitlines()[0]
    assert collector.user_id in body


def test_unlinked_enumerator_shows_placeholder(client, django_user_model):
    uc = UseCase.objects.create(code="NOLINK", name="No link")
    Enumerator.objects.create(use_case=uc, enid="ENX")  # no user
    coord = django_user_model.objects.create_user("c2@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=coord, use_case=uc, role=Role.TRIAL_COORDINATOR)
    client.force_login(coord)
    resp = client.get(reverse("dashboards:tab_enumerators", args=[uc.code]))
    assert resp.status_code == 200
    assert b"unlinked" in resp.content
