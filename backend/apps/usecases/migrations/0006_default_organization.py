"""Backfill: put all existing data into one default Organization.

Existing deployments become a single tenant — every region, use case, and user
joins the default org — so nothing is orphaned and behaviour is unchanged until
more organizations are created.
"""
from __future__ import annotations

from django.db import migrations

DEFAULT_CODE = "default"
DEFAULT_NAME = "Default Organization"


def create_default_org(apps, schema_editor):
    Organization = apps.get_model("usecases", "Organization")
    Region = apps.get_model("usecases", "Region")
    UseCase = apps.get_model("usecases", "UseCase")
    User = apps.get_model("accounts", "User")

    # Only seed a default if there is existing data to home; a brand-new install
    # creates its first org explicitly.
    has_data = Region.objects.exists() or UseCase.objects.exists() or User.objects.exists()
    if not has_data:
        return

    org, _ = Organization.objects.get_or_create(
        code=DEFAULT_CODE, defaults={"name": DEFAULT_NAME}
    )
    Region.objects.filter(organization__isnull=True).update(organization=org)
    UseCase.objects.filter(organization__isnull=True).update(organization=org)
    User.objects.filter(organization__isnull=True).update(organization=org)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("usecases", "0005_organization_alter_region_code_region_organization_and_more"),
        ("accounts", "0003_user_organization"),
    ]

    operations = [migrations.RunPython(create_default_org, noop)]
