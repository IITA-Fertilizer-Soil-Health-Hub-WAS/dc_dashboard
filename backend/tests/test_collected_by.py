"""collected_by resolution: every submission traces to a platform account.

Two paths — the mobile app stamps the collector's UserID directly, or (ONA era)
the submission is attributed via the enumerator's linked account.
"""
from __future__ import annotations

import pytest

from apps.ingestion.sync import sync_project
from apps.submissions.models import Enumerator, Submission
from apps.usecases.models import FieldMapping, FormDefinition, Project

pytestmark = pytest.mark.django_db


def _form_with_mappings(uc, pairs):
    form = FormDefinition.objects.create(
        project=uc, ona_form_id=99, role=FormDefinition.Role.VALIDATION
    )
    for order, (target, src) in enumerate(pairs):
        FieldMapping.objects.create(
            form=form, target_field=target, source_paths=[src], order=order
        )
    return form


def test_collected_by_from_stamped_userid(django_user_model):
    """A submission carrying the collector's platform UserID is attributed to them."""
    collector = django_user_model.objects.create_user("col@x.org", "pw", is_active=True)
    uc = Project.objects.create(code="UC1", name="UC1")
    _form_with_mappings(uc, [("ENID", "enid"), ("USERID", "uid"), ("event_key", "ev")])

    class Fake:
        def get_data(self, fid):
            return [{"_uuid": "u1", "enid": "EN1", "uid": collector.user_id, "ev": "Event1"}]

    sync_project(uc, client=Fake())
    sub = Submission.objects.get(project=uc, ona_uuid="u1")
    assert sub.collected_by == collector


def test_collected_by_bridges_via_enumerator(django_user_model):
    """With no stamped UserID, attribution falls back to the enumerator's account."""
    account = django_user_model.objects.create_user("en@x.org", "pw", is_active=True)
    uc = Project.objects.create(code="UC2", name="UC2")
    # Pre-link an enumerator to the account (admin would do this during ONA era).
    Enumerator.objects.create(project=uc, enid="EN9", user=account)
    _form_with_mappings(uc, [("ENID", "enid"), ("event_key", "ev")])

    class Fake:
        def get_data(self, fid):
            return [{"_uuid": "u2", "enid": "EN9", "ev": "Event1"}]

    sync_project(uc, client=Fake())
    sub = Submission.objects.get(project=uc, ona_uuid="u2")
    assert sub.collected_by == account


def test_collected_by_none_when_unresolved():
    """No stamped UserID and an unlinked enumerator leaves collected_by empty."""
    uc = Project.objects.create(code="UC3", name="UC3")
    _form_with_mappings(uc, [("ENID", "enid"), ("event_key", "ev")])

    class Fake:
        def get_data(self, fid):
            return [{"_uuid": "u3", "enid": "EN-UNLINKED", "ev": "Event1"}]

    sync_project(uc, client=Fake())
    sub = Submission.objects.get(project=uc, ona_uuid="u3")
    assert sub.collected_by is None


def test_stamped_userid_wins_over_enumerator_bridge(django_user_model):
    """When both signals exist, the stamped UserID (the end state) takes priority."""
    stamped = django_user_model.objects.create_user("stamp@x.org", "pw", is_active=True)
    bridged = django_user_model.objects.create_user("bridge@x.org", "pw", is_active=True)
    uc = Project.objects.create(code="UC4", name="UC4")
    Enumerator.objects.create(project=uc, enid="EN4", user=bridged)
    _form_with_mappings(uc, [("ENID", "enid"), ("USERID", "uid"), ("event_key", "ev")])

    class Fake:
        def get_data(self, fid):
            return [{"_uuid": "u4", "enid": "EN4", "uid": stamped.user_id, "ev": "Event1"}]

    sync_project(uc, client=Fake())
    sub = Submission.objects.get(project=uc, ona_uuid="u4")
    assert sub.collected_by == stamped
