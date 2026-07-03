"""Bulk-linking Enumerators to platform accounts by phone/name."""
from __future__ import annotations

import pytest

from apps.ingestion.sync import sync_project
from apps.projects.models import FieldMapping, FormDefinition, Project
from apps.submissions.linking import link_enumerators
from apps.submissions.models import Enumerator, Submission

pytestmark = pytest.mark.django_db


@pytest.fixture
def project():
    return Project.objects.create(code="UC", name="UC")


def test_match_by_phone(django_user_model, project):
    user = django_user_model.objects.create_user(
        "a@x.org", "pw", full_name="Aline Uwase", phone="+250788000000"
    )
    en = Enumerator.objects.create(
        project=project, enid="EN1", first_name="Different", surname="Name",
        phone="0788 000 000",  # same number, different formatting
    )

    report = link_enumerators(apply=True)
    en.refresh_from_db()
    assert en.user == user
    assert report.matched == 1
    assert report.proposals[0].reason == "phone"


def test_match_by_name_when_no_phone(django_user_model, project):
    user = django_user_model.objects.create_user("b@x.org", "pw", full_name="John Doe")
    en = Enumerator.objects.create(
        project=project, enid="EN2", first_name="john", surname="DOE"
    )
    report = link_enumerators(apply=True)
    en.refresh_from_db()
    assert en.user == user
    assert report.matched == 1
    assert report.proposals[0].reason == "name"


def test_dry_run_does_not_persist(django_user_model, project):
    django_user_model.objects.create_user("c@x.org", "pw", phone="0788111222")
    en = Enumerator.objects.create(project=project, enid="EN3", phone="0788111222")
    report = link_enumerators(apply=False)
    en.refresh_from_db()
    assert en.user is None  # nothing written
    assert report.matched == 1  # but reported


def test_ambiguous_match_not_linked(django_user_model, project):
    django_user_model.objects.create_user("d1@x.org", "pw", phone="0788333444")
    django_user_model.objects.create_user("d2@x.org", "pw", phone="0788333444")
    en = Enumerator.objects.create(project=project, enid="EN4", phone="0788333444")
    report = link_enumerators(apply=True)
    en.refresh_from_db()
    assert en.user is None
    assert report.ambiguous == 1
    assert report.matched == 0


def test_already_linked_skipped_without_overwrite(django_user_model, project):
    u1 = django_user_model.objects.create_user("e1@x.org", "pw", phone="0788555666")
    u2 = django_user_model.objects.create_user("e2@x.org", "pw", phone="0788555666")
    en = Enumerator.objects.create(project=project, enid="EN5", phone="0788555666", user=u1)

    # Ambiguous now (two users share the phone), but already-linked => skipped.
    report = link_enumerators(apply=True, overwrite=False)
    en.refresh_from_db()
    assert en.user == u1
    assert report.already == 1
    assert report.matched == 0
    # silence unused-var lint while documenting the collision
    assert u2.phone == u1.phone


def test_unmatched_when_no_signal(project):
    Enumerator.objects.create(project=project, enid="EN6")  # no phone, no name
    report = link_enumerators(apply=True)
    assert report.unmatched == 1
    assert report.matched == 0


def test_scope_to_one_project(django_user_model):
    uc1 = Project.objects.create(code="UC1", name="UC1")
    uc2 = Project.objects.create(code="UC2", name="UC2")
    django_user_model.objects.create_user("f@x.org", "pw", phone="0788777888")
    en1 = Enumerator.objects.create(project=uc1, enid="E1", phone="0788777888")
    en2 = Enumerator.objects.create(project=uc2, enid="E2", phone="0788777888")

    link_enumerators(apply=True, project=uc1)
    en1.refresh_from_db()
    en2.refresh_from_db()
    assert en1.user is not None
    assert en2.user is None  # out of scope


def test_link_then_sync_populates_collected_by(django_user_model, project):
    """End-to-end: link by phone, then a sync stamps collected_by via the bridge."""
    user = django_user_model.objects.create_user("g@x.org", "pw", phone="0788999000")
    Enumerator.objects.create(project=project, enid="EN7", phone="0788999000")
    link_enumerators(apply=True)

    form = FormDefinition.objects.create(
        project=project, ona_form_id=42, role=FormDefinition.Role.VALIDATION
    )
    for order, (target, src) in enumerate([("ENID", "enid"), ("event_key", "ev")]):
        FieldMapping.objects.create(form=form, target_field=target, source_paths=[src], order=order)

    class Fake:
        def get_data(self, fid):
            return [{"_uuid": "uu", "enid": "EN7", "ev": "Event1"}]

    sync_project(project, client=Fake())
    sub = Submission.objects.get(project=project, ona_uuid="uu")
    assert sub.collected_by == user
