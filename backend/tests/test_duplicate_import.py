"""Guard against onboarding the same collection-server project twice under
different names (the cause of identical forms under two Fieldbase projects)."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.config_admin.loader import check_duplicate_import
from apps.projects.models import FormDefinition, Organization, Project

pytestmark = pytest.mark.django_db


def _cfg(code, ona_id):
    return {"project": {"code": code, "name": code}, "forms": [{"ona_form_id": ona_id}]}


def test_duplicate_form_id_flagged_across_projects():
    org = Organization.objects.create(code="o", name="O")
    p = Project.objects.create(code="GHANA", name="G", organization=org)
    FormDefinition.objects.create(project=p, ona_form_id=855917,
                                  role=FormDefinition.Role.VALIDATION)
    # Same ONA form under a *different* code → flagged.
    warns = check_duplicate_import(_cfg("TOGO", 855917))
    assert warns and "GHANA" in warns[0]
    # Re-importing the SAME code (idempotent update) → not flagged.
    assert check_duplicate_import(_cfg("GHANA", 855917)) == []
    # A genuinely new form id → not flagged.
    assert check_duplicate_import(_cfg("TOGO", 999999)) == []


def test_wizard_blocks_duplicate_then_allows_override(client, django_user_model):
    org = Organization.objects.create(code="o", name="O")
    admin = django_user_model.objects.create_superuser("a@x.org", "pw")
    owner = django_user_model.objects.create_user("own@x.org", "pw", is_active=True)
    existing = Project.objects.create(code="GHANA", name="G", organization=org)
    FormDefinition.objects.create(project=existing, ona_form_id=855917,
                                  role=FormDefinition.Role.VALIDATION)
    client.force_login(admin)

    post = {
        "code": "TOGO", "name": "Togo", "organization": "o", "owner": owner.email,
        "backend": "ONA", "form_count": "1", "form-0-id": "855917",
        "form-0-role": "VALIDATION",
    }
    # Without confirmation → re-render with the duplicate warning, nothing created.
    resp = client.post(reverse("console:onboard"), post)
    assert resp.status_code == 200
    assert "duplicate import" in resp.content.decode().lower()
    assert not Project.objects.filter(code="TOGO").exists()

    # With the override → the project is created.
    resp2 = client.post(reverse("console:onboard"), {**post, "confirm_duplicate": "1"})
    assert resp2.status_code == 302
    assert Project.objects.filter(code="TOGO").exists()
