"""Bootstrap an institution (tenant).

On a fresh self-hosted (single-tenant) deployment, create the one organization
everything will belong to; on the central platform, add a new institution.

    python manage.py create_organization "Soil Health Hub" --code shh
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from apps.usecases.models import Organization


class Command(BaseCommand):
    help = "Create an Organization (institution / tenant)."

    def add_arguments(self, parser):
        parser.add_argument("name", help="Display name, e.g. 'Soil Health Hub'.")
        parser.add_argument("--code", help="Short slug (defaults to a slug of the name).")

    def handle(self, *args, **options):
        name = options["name"].strip()
        code = (options["code"] or slugify(name))[:32]
        if Organization.objects.filter(code=code).exists():
            raise CommandError(f"An organization with code '{code}' already exists.")
        org = Organization.objects.create(code=code, name=name)
        self.stdout.write(self.style.SUCCESS(f"Created organization '{org.name}' (code={org.code})."))
