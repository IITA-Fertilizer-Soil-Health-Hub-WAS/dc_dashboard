"""Sync a project's ONA data into the database (ops / backfill / CI).

    python manage.py sync_project SNS-RWANDA
    python manage.py sync_project --all
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.sync import sync_project
from apps.projects.models import Project
from apps.validation.engine import run_for_project


class Command(BaseCommand):
    help = "Pull ONA data for a project and upsert submissions."

    def add_arguments(self, parser):
        parser.add_argument("code", nargs="?", help="Project code")
        parser.add_argument("--all", action="store_true", help="Sync all active projects")

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
            stats = sync_project(uc)
            vstats = run_for_project(uc)
            self.stdout.write(self.style.SUCCESS(
                f"{uc.code}: +{stats.created} new, ~{stats.updated} updated, "
                f"={stats.unchanged} unchanged, {stats.enumerators} enumerators, "
                f"{stats.units} units, {stats.skipped_test} test-skipped | "
                f"flags +{vstats.opened} / resolved {vstats.resolved}, "
                f"{vstats.flagged_submissions} submissions flagged"
            ))
            for err in stats.errors:
                self.stderr.write(self.style.WARNING(f"  ! {err}"))
