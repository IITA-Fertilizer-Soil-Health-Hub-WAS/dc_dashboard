"""Cache each form's field schema (question labels + section groups) so the
review screen renders submissions with human labels instead of raw ODK paths.

    python manage.py sync_form_schemas SNS-RWANDA
    python manage.py sync_form_schemas --all
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.form_schema import sync_project_schemas
from apps.projects.models import Project


class Command(BaseCommand):
    help = "Fetch + cache form field schemas (labels/groups) for a project."

    def add_arguments(self, parser):
        parser.add_argument("code", nargs="?", help="Project code")
        parser.add_argument("--all", action="store_true", help="All active projects")

    def handle(self, *args, **options):
        if options["all"]:
            qs = Project.objects.filter(is_active=True)
        elif options["code"]:
            qs = Project.objects.filter(code=options["code"])
            if not qs.exists():
                raise CommandError(f"Unknown project: {options['code']}")
        else:
            raise CommandError("Provide a project code or --all")

        for uc in qs:
            result = sync_project_schemas(uc)
            parts = ", ".join(f"{ref}={n}" for ref, n in result.items()) or "no forms"
            self.stdout.write(self.style.SUCCESS(f"{uc.code}: {parts}"))
