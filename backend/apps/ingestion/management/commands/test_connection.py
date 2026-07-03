"""Test a use case's data-collection backend connection (discovery).

    python manage.py test_connection SNS-RWANDA

Works for any backend (ONA, KoboToolbox, ODK Central, …). For Kobo/ODK Central
this is also how you validate discovery against a real instance: configure the
use case's DataSource (backend, base_url, token, config.project_id) and run this.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.backends.registry import get_backend_for
from apps.usecases.models import Project


class Command(BaseCommand):
    help = "Test a use case's backend connection by listing its projects/forms."

    def add_arguments(self, parser):
        parser.add_argument("code", help="Use case code")

    def handle(self, *args, **options):
        try:
            uc = Project.objects.get(code=options["code"])
        except Project.DoesNotExist as exc:
            raise CommandError(f"Unknown use case: {options['code']}") from exc

        backend = get_backend_for(uc)
        self.stdout.write(f"{uc.code}: backend = {backend.label} ({backend.type})")
        self.stdout.write(f"base_url = {backend.base_url or '(default)'}")

        try:
            if backend.supports_discovery:
                projects = backend.discover_projects()
                self.stdout.write(self.style.SUCCESS(
                    f"OK — reachable. Discovered {len(projects)} project(s):"))
                for p in projects[:15]:
                    self.stdout.write(f"  • {p.name}  ({len(p.forms)} forms)")
            else:
                forms = backend.list_forms()
                self.stdout.write(self.style.SUCCESS(f"OK — {len(forms)} form(s) reachable."))
        except Exception as exc:
            raise CommandError(f"Connection FAILED: {exc}") from exc
