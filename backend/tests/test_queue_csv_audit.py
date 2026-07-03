"""My queue, CSV mapping import, and audit-log export."""
from __future__ import annotations

import pytest

from apps.projects.models import FormDefinition, Project
from apps.rbac.models import ProjectMembership, Role
from apps.review import services
from apps.submissions.models import Submission

pytestmark = pytest.mark.django_db


@pytest.fixture
def uc():
    return Project.objects.create(code="UC", name="UC")


@pytest.fixture
def form(uc):
    return FormDefinition.objects.create(project=uc, ona_form_id=1,
                                         role=FormDefinition.Role.VALIDATION)


@pytest.fixture
def coordinator(django_user_model, uc):
    u = django_user_model.objects.create_user("c@x.org", "pw", is_active=True)
    ProjectMembership.objects.create(user=u, project=uc, role=Role.TRIAL_COORDINATOR)
    return u


@pytest.fixture
def staff(django_user_model):
    return django_user_model.objects.create_superuser("admin@x.org", "pw")


# ---- CSV mapping import ----
def test_csv_mapping_import(client, staff, form):
    client.force_login(staff)
    csv = "target,source,transform,required,order\nENID,intro/enumerator_id,DIRECT,true,0\nHHID,intro/hh;intro/barcode,COALESCE,false,1\n"
    resp = client.post(f"/manage/forms/{form.pk}/mappings/", {"action": "import_csv", "csv": csv})
    assert resp.status_code == 302
    enid = form.mappings.get(target_field="ENID")
    assert enid.source_paths == ["intro/enumerator_id"] and enid.required is True
    hh = form.mappings.get(target_field="HHID")
    assert hh.source_paths == ["intro/hh", "intro/barcode"] and hh.transform == "COALESCE"


def test_csv_import_skips_header_and_blanks(client, staff, form):
    client.force_login(staff)
    csv = "target,source\n\nCROP,planting/crop\n"
    client.post(f"/manage/forms/{form.pk}/mappings/", {"action": "import_csv", "csv": csv})
    assert form.mappings.count() == 1
    assert form.mappings.first().target_field == "CROP"


# ---- Audit export ----
def test_audit_export_csv(client, uc, form, coordinator):
    s = Submission.objects.create(project=uc, form=form, ona_uuid="A1", content_hash="h")
    services.decline(coordinator, s, note="bad id")
    client.force_login(coordinator)
    resp = client.get(f"/project/{uc.code}/audit.csv")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "text/csv"
    body = resp.content.decode()
    assert "timestamp" in body and "DECLINE" in body and "bad id" in body
