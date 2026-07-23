"""Learn-by-doing demo project + the in-app Help / enumerator guide."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.projects.models import Project
from apps.submissions.models import Submission
from apps.validation.models import ValidationFlag

pytestmark = pytest.mark.django_db


def test_create_demo_project_has_data_rules_and_flags(django_user_model):
    from apps.console.demo import create_demo_project

    admin = django_user_model.objects.create_superuser("a@x.org", "pw")
    uc = create_demo_project(owner=admin)
    assert uc.code.startswith("DEMO-")
    assert Submission.objects.filter(project=uc).count() == 24
    assert uc.rules.count() == 3
    # The seeded problems (duplicate id, out-of-range pH, an outlier) get flagged.
    assert ValidationFlag.objects.filter(submission__project=uc,
                                         status=ValidationFlag.Status.OPEN).exists()


def test_demo_view_is_staff_only(client, django_user_model):
    admin = django_user_model.objects.create_superuser("a@x.org", "pw")
    client.force_login(admin)
    resp = client.post(reverse("console:demo_project"))
    assert resp.status_code == 302
    assert Project.objects.filter(code__startswith="DEMO-").exists()

    member = django_user_model.objects.create_user("m@x.org", "pw", is_active=True)
    client.force_login(member)
    assert client.post(reverse("console:demo_project")).status_code == 403


def test_help_and_enumerator_guide_render(client, django_user_model):
    user = django_user_model.objects.create_user("u@x.org", "pw", is_active=True)
    client.force_login(user)
    assert client.get(reverse("console:help")).status_code == 200
    guide = client.get(reverse("console:enumerator_guide"))
    assert guide.status_code == 200 and "Enumerator quick guide" in guide.content.decode()
