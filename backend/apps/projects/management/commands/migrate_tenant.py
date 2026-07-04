"""Apply migrations to one institution's dedicated database.

Registers the org's connection (from its alias / database_url) and runs Django's
migrate against it, creating only the tenant-app tables there.
"""
from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from apps.projects.db_routing import ensure_tenant_connection
from apps.projects.models import Organization


class Command(BaseCommand):
    help = "Migrate an institution's dedicated database."

    def add_arguments(self, parser):
        parser.add_argument("org_code", help="Organization code")

    def handle(self, *args, **opts):
        org = Organization.objects.filter(code=opts["org_code"]).first()
        if org is None:
            raise CommandError(f"No institution with code {opts['org_code']!r}.")
        alias = ensure_tenant_connection(org)
        if not alias or alias == "default":
            self.stdout.write(
                f"{org.code} has no dedicated database (uses the shared DB) — nothing to do."
            )
            return
        self.stdout.write(f"Migrating {org.code} → database '{alias}'…")
        call_command("migrate", database=alias, verbosity=1)
        self.stdout.write(self.style.SUCCESS(f"{org.code} database is up to date."))
