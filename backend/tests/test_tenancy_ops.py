"""Tenancy operations: onboarding org assignment, create/export commands."""
from __future__ import annotations

import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.config_admin.loader import import_config
from apps.submissions.models import Enumerator
from apps.usecases.models import FieldMapping, FormDefinition, Organization, Project

pytestmark = pytest.mark.django_db


def test_create_organization_command():
    out = StringIO()
    call_command("create_organization", "Soil Health Hub", "--code", "shh", stdout=out)
    org = Organization.objects.get(code="shh")
    assert org.name == "Soil Health Hub"


def test_create_organization_rejects_duplicate():
    Organization.objects.create(code="dup", name="Dup")
    with pytest.raises(CommandError):
        call_command("create_organization", "Another", "--code", "dup")


def test_import_config_assigns_named_org():
    org = Organization.objects.create(code="inst", name="Institution")
    uc = import_config({"project": {"code": "P1", "name": "Project 1", "organization": "inst"}})
    assert uc.organization == org


def test_import_config_falls_back_to_single_org():
    org = Organization.objects.create(code="only", name="Only Org")
    uc = import_config({"project": {"code": "P2", "name": "Project 2"}})
    assert uc.organization == org  # exactly one org → the default tenant


def test_export_organization_roundtrip(django_user_model):
    org = Organization.objects.create(code="exp", name="Exportable")
    uc = Project.objects.create(code="EXP-UC", name="Exp UC", organization=org)
    form = FormDefinition.objects.create(
        project=uc, ona_form_id=1, role=FormDefinition.Role.VALIDATION
    )
    FieldMapping.objects.create(form=form, target_field="ENID", source_paths=["enid"], order=0)
    Enumerator.objects.create(project=uc, enid="EN1")
    django_user_model.objects.create_user("u@x.org", "pw", is_active=True, organization=org)

    out, err = StringIO(), StringIO()
    call_command("export_organization", "exp", stdout=out, stderr=err)
    payload = json.loads(out.getvalue())

    models = {row["model"] for row in payload}
    assert "usecases.organization" in models
    assert "usecases.project" in models
    assert "usecases.formdefinition" in models
    assert "submissions.enumerator" in models
    assert "accounts.user" in models
    # The use case row carries its organization FK so the import stays owned.
    uc_row = next(r for r in payload if r["model"] == "usecases.project")
    assert uc_row["fields"]["organization"] == str(org.pk)


def test_export_unknown_org_errors():
    with pytest.raises(CommandError):
        call_command("export_organization", "missing")


def test_export_excludes_other_orgs_data():
    a = Organization.objects.create(code="a", name="A")
    b = Organization.objects.create(code="b", name="B")
    Project.objects.create(code="A-UC", name="A", organization=a)
    Project.objects.create(code="B-UC", name="B", organization=b)

    out = StringIO()
    call_command("export_organization", "a", stdout=out)
    codes = {
        r["fields"].get("code")
        for r in json.loads(out.getvalue())
        if r["model"] == "usecases.project"
    }
    assert codes == {"A-UC"}  # B's project is not in A's export
