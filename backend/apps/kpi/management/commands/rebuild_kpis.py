"""Rebuild the daily KPI aggregates (all projects, or one with --use-case)."""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.kpi.aggregate import rebuild_all_kpis, rebuild_use_case_kpis
from apps.usecases.models import UseCase


class Command(BaseCommand):
    help = "Materialise the daily KPI aggregates from ingested submissions."

    def add_arguments(self, parser):
        parser.add_argument("--use-case", dest="use_case", help="Limit to one UseCase code.")

    def handle(self, *args, **options):
        if options["use_case"]:
            uc = UseCase.objects.filter(code=options["use_case"]).first()
            if uc is None:
                raise CommandError(f"Unknown use case: {options['use_case']}")
            result = rebuild_use_case_kpis(uc)
        else:
            result = rebuild_all_kpis()
        self.stdout.write(self.style.SUCCESS(f"KPIs rebuilt: {result}"))
