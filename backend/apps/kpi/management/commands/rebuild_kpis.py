"""Rebuild the daily KPI aggregates (all projects, or one with --project)."""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.kpi.aggregate import rebuild_all_kpis, rebuild_project_kpis
from apps.projects.models import Project


class Command(BaseCommand):
    help = "Materialise the daily KPI aggregates from ingested submissions."

    def add_arguments(self, parser):
        parser.add_argument("--project", dest="project", help="Limit to one Project code.")

    def handle(self, *args, **options):
        if options["project"]:
            uc = Project.objects.filter(code=options["project"]).first()
            if uc is None:
                raise CommandError(f"Unknown project: {options['project']}")
            result = rebuild_project_kpis(uc)
        else:
            result = rebuild_all_kpis()
        self.stdout.write(self.style.SUCCESS(f"KPIs rebuilt: {result}"))
