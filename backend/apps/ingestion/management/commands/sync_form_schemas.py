"""Cache each form's field schema (question labels + section groups) so the
review screen renders submissions with human labels instead of raw ODK paths.

    python manage.py sync_form_schemas SNS-RWANDA
    python manage.py sync_form_schemas --all
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.form_schema import sync_use_case_schemas
from apps.usecases.models import UseCase


class Command(BaseCommand):
    help = "Fetch + cache form field schemas (labels/groups) for a use case."

    def add_arguments(self, parser):
        parser.add_argument("code", nargs="?", help="Use case code")
        parser.add_argument("--all", action="store_true", help="All active use cases")

    def handle(self, *args, **options):
        if options["all"]:
            qs = UseCase.objects.filter(is_active=True)
        elif options["code"]:
            qs = UseCase.objects.filter(code=options["code"])
            if not qs.exists():
                raise CommandError(f"Unknown use case: {options['code']}")
        else:
            raise CommandError("Provide a use case code or --all")

        for uc in qs:
            result = sync_use_case_schemas(uc)
            parts = ", ".join(f"{ref}={n}" for ref, n in result.items()) or "no forms"
            self.stdout.write(self.style.SUCCESS(f"{uc.code}: {parts}"))
