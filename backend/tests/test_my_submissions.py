"""Enumerator self-view: 'My submissions' shows only the user's own records."""
from __future__ import annotations

from datetime import date

import pytest
from django.urls import reverse

from apps.submissions.models import Enumerator, Submission
from apps.usecases.models import FormDefinition, Organization, Project

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(django_user_model):
    org = Organization.objects.create(code="o", name="O")
    uc = Project.objects.create(code="PROJ-A", name="A", organization=org)
    form = FormDefinition.objects.create(project=uc, ona_form_id=5,
                                         role=FormDefinition.Role.VALIDATION)
    me = django_user_model.objects.create_user("me@x.org", "pw", is_active=True, organization=org)
    other = django_user_model.objects.create_user("other@x.org", "pw", is_active=True, organization=org)
    # One submission collected by me (direct), one via my linked enumerator, one by someone else.
    Submission.objects.create(project=uc, form=form, ona_uuid="mine-direct",
                              content_hash="h", collected_by=me, event_date=date.today())
    en = Enumerator.objects.create(project=uc, enid="EN-ME", user=me)
    Submission.objects.create(project=uc, form=form, ona_uuid="mine-via-enum",
                              content_hash="h", enumerator=en, event_date=date.today())
    Submission.objects.create(project=uc, form=form, ona_uuid="not-mine",
                              content_hash="h", collected_by=other, event_date=date.today())
    return {"me": me, "other": other}


def test_my_submissions_scoped_to_own_records(client, world):
    client.force_login(world["me"])
    resp = client.get(reverse("dashboards:my_submissions"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "mine-direct" not in body  # uuids aren't shown, but count is
    # Two records are mine (direct + via enumerator); the other user's is excluded.
    assert resp.context["total"] == 2


def test_other_user_does_not_see_my_submissions(client, world):
    client.force_login(world["other"])
    resp = client.get(reverse("dashboards:my_submissions"))
    assert resp.status_code == 200
    assert resp.context["total"] == 1  # only their own
