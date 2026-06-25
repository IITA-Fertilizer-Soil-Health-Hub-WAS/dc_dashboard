"""Sync a use case's ONA data into the database (ops / backfill / CI).

    python manage.py sync_usecase SNS-RWANDA
    python manage.py sync_usecase --all
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.sync import sync_use_case
from apps.usecases.models import UseCase
from apps.validation.engine import run_for_use_case


class Command(BaseCommand):
    help = "Pull ONA data for a use case and upsert submissions."

    def add_arguments(self, parser):
        parser.add_argument("code", nargs="?", help="Use case code")
        parser.add_argument("--all", action="store_true", help="Sync all active use cases")

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
            stats = sync_use_case(uc)
            vstats = run_for_use_case(uc)
            self.stdout.write(self.style.SUCCESS(
                f"{uc.code}: +{stats.created} new, ~{stats.updated} updated, "
                f"={stats.unchanged} unchanged, {stats.enumerators} enumerators, "
                f"{stats.households} households, {stats.skipped_test} test-skipped | "
                f"flags +{vstats.opened} / resolved {vstats.resolved}, "
                f"{vstats.flagged_submissions} submissions flagged"
            ))
            for err in stats.errors:
                self.stderr.write(self.style.WARNING(f"  ! {err}"))
