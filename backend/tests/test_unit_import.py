"""Feature B, Stage B2: CSV import of collection units (scoped)."""
from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.fieldwork.imports import import_collection_units
from apps.fieldwork.models import CollectionUnit
from apps.rbac.models import Role, UseCaseMembership
from apps.usecases.models import Organization, Project

pytestmark = pytest.mark.django_db


@pytest.fixture
def uc():
    return Project.objects.create(code="UC", name="UC")


def test_import_creates_and_keeps_extra_columns(uc):
    csv_text = (
        "code,name,lat,lon,district,variety\n"
        "HH1,Alice,-1.95,30.06,Gasabo,maize\n"
        "HH2,Bob,,,Kicukiro,rice\n"
    )
    report = import_collection_units(uc, csv_text)
    assert report.created == 2 and report.updated == 0
    u1 = CollectionUnit.objects.get(project=uc, code="HH1")
    assert u1.name == "Alice"
    assert float(u1.lat) == pytest.approx(-1.95)
    assert u1.district == "Gasabo"
    assert u1.attributes == {"variety": "maize"}  # unknown column -> attributes


def test_reimport_updates_by_code(uc):
    import_collection_units(uc, "code,name\nHH1,Alice\n")
    report = import_collection_units(uc, "code,name\nHH1,Alice Updated\n")
    assert report.created == 0 and report.updated == 1
    assert CollectionUnit.objects.get(project=uc, code="HH1").name == "Alice Updated"


def test_import_skips_rows_without_code(uc):
    report = import_collection_units(uc, "code,name\n,No code\nHH1,Has code\n")
    assert report.created == 1 and report.skipped == 1


def test_import_requires_code_column(uc):
    report = import_collection_units(uc, "name,district\nAlice,Gasabo\n")
    assert report.errors
    assert CollectionUnit.objects.count() == 0


def test_import_view_coordinator_scoped(client, django_user_model):
    org = Organization.objects.create(code="o", name="O")
    mine = Project.objects.create(code="MINE", name="Mine", organization=org)
    other = Project.objects.create(code="OTHER", name="Other", organization=org)
    coord = django_user_model.objects.create_user("c@x.org", "pw", is_active=True, organization=org)
    UseCaseMembership.objects.create(user=coord, project=mine, role=Role.TRIAL_COORDINATOR)
    client.force_login(coord)

    # The picker only offers their project.
    resp = client.get(reverse("console:import_units"))
    assert resp.status_code == 200
    assert b"MINE" in resp.content and b"OTHER" not in resp.content

    # Import into their own project works.
    csv = SimpleUploadedFile("u.csv", b"code,name\nHH1,Alice\n", content_type="text/csv")
    resp = client.post(reverse("console:import_units"),
                       {"project": str(mine.pk), "csv": csv})
    assert resp.status_code == 302
    assert CollectionUnit.objects.filter(project=mine, code="HH1").exists()

    # Posting another project's id imports nothing (scoped out).
    csv2 = SimpleUploadedFile("u.csv", b"code,name\nHHX,X\n", content_type="text/csv")
    resp = client.post(reverse("console:import_units"),
                       {"project": str(other.pk), "csv": csv2})
    assert resp.status_code == 200  # re-renders with an error
    assert not CollectionUnit.objects.filter(project=other).exists()


def test_import_view_blocked_for_viewer(client, django_user_model):
    uc = Project.objects.create(code="V", name="V")
    viewer = django_user_model.objects.create_user("v@x.org", "pw", is_active=True)
    UseCaseMembership.objects.create(user=viewer, project=uc, role=Role.VIEWER)
    client.force_login(viewer)
    assert client.get(reverse("console:import_units")).status_code == 403
