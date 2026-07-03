"""collected_by surfaces in the dashboards: ranking, data preview, and exports."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.ingestion.sync import sync_project
from apps.projects.models import FieldMapping, FormDefinition, Project
from apps.rbac.models import Role, UseCaseMembership
from apps.review.models import Review, ReviewAction, ReviewActionLog, ReviewState
from apps.submissions.models import Enumerator, Submission

pytestmark = pytest.mark.django_db


@pytest.fixture
def attributed(django_user_model):
    """A use case with one submission collected by a linked account, approved."""
    collector = django_user_model.objects.create_user(
        "collector@x.org", "pw", full_name="Field Collector", is_active=True
    )
    uc = Project.objects.create(code="ATTR", name="Attribution UC")
    Enumerator.objects.create(project=uc, enid="EN1", user=collector)
    form = FormDefinition.objects.create(
        project=uc, ona_form_id=1, role=FormDefinition.Role.VALIDATION
    )
    for order, (t, s) in enumerate([("ENID", "enid"), ("HHID", "hhid"), ("event_key", "ev")]):
        FieldMapping.objects.create(form=form, target_field=t, source_paths=[s], order=order)

    class Fake:
        def get_data(self, fid):
            return [{"_uuid": "u1", "enid": "EN1", "hhid": "HH1", "ev": "Event1"}]

    sync_project(uc, client=Fake())
    sub = Submission.objects.get(project=uc, ona_uuid="u1")
    assert sub.collected_by == collector  # bridge populated it

    Review.objects.update_or_create(
        submission=sub, defaults={"state": ReviewState.APPROVED}
    )
    ReviewActionLog.objects.create(
        submission=sub, action=ReviewAction.QC_APPROVE,
        from_state=ReviewState.QC_PENDING, to_state=ReviewState.APPROVED,
    )

    coord = django_user_model.objects.create_user("co@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=coord, project=uc, role=Role.TRIAL_COORDINATOR)
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


def test_collectors_ranking_lists_account(client, attributed):
    uc, collector, coord = attributed
    client.force_login(coord)
    resp = client.get(reverse("dashboards:tab_enumerators", args=[uc.code]))
    assert resp.status_code == 200
    assert b"Collectors" in resp.content
    assert collector.user_id.encode() in resp.content
    assert b"Field Collector" in resp.content  # full_name in the collectors table


def test_summary_attribution_coverage(client, attributed):
    uc, collector, coord = attributed
    client.force_login(coord)
    resp = client.get(reverse("dashboards:tab_summary", args=[uc.code]))
    assert resp.status_code == 200
    # The single submission is attributed -> 100%.
    assert b"100%" in resp.content
    assert b"Attributed to a user" in resp.content
    assert b"Identity coverage" in resp.content


def test_attribution_zero_when_unlinked(client, django_user_model):
    uc = Project.objects.create(code="ZERO", name="Zero")
    Enumerator.objects.create(project=uc, enid="ENZ")  # not linked
    form = FormDefinition.objects.create(
        project=uc, ona_form_id=2, role=FormDefinition.Role.VALIDATION
    )
    for order, (t, s) in enumerate([("ENID", "enid"), ("event_key", "ev")]):
        FieldMapping.objects.create(form=form, target_field=t, source_paths=[s], order=order)

    class Fake:
        def get_data(self, fid):
            return [{"_uuid": "z1", "enid": "ENZ", "ev": "Event1"}]

    sync_project(uc, client=Fake())
    coord = django_user_model.objects.create_user("z@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=coord, project=uc, role=Role.TRIAL_COORDINATOR)
    client.force_login(coord)
    resp = client.get(reverse("dashboards:tab_summary", args=[uc.code]))
    assert resp.status_code == 200
    assert b"0%" in resp.content


def test_unlinked_enumerator_shows_placeholder(client, django_user_model):
    uc = Project.objects.create(code="NOLINK", name="No link")
    Enumerator.objects.create(project=uc, enid="ENX")  # no user
    coord = django_user_model.objects.create_user("c2@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=coord, project=uc, role=Role.TRIAL_COORDINATOR)
    client.force_login(coord)
    resp = client.get(reverse("dashboards:tab_enumerators", args=[uc.code]))
    assert resp.status_code == 200
    assert b"unlinked" in resp.content
