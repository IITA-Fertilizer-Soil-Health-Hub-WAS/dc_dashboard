"""Publish the coordinator plot-anchor form and/or fold captured anchors back.

    manage.py sync_plot_anchors PROJ-A               # pull captured anchors
    manage.py sync_plot_anchors PROJ-A --publish     # (re)publish the field form
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.fieldwork.anchor_form import apply_anchor_submissions, publish_anchor_form
from apps.usecases.models import Project


class Command(BaseCommand):
    help = "Publish the plot-anchor form and/or apply captured anchors for a project."

    def add_arguments(self, parser):
        parser.add_argument("project", help="Project code")
        parser.add_argument("--publish", action="store_true",
                            help="(Re)publish the anchor form to the server")

    def handle(self, *args, **opts):
        try:
            uc = Project.objects.get(code=opts["project"])
        except Project.DoesNotExist as e:
            raise CommandError(f"No use case with code {opts['project']!r}") from e

        if opts["publish"]:
            _, result = publish_anchor_form(uc)
            if result.ok:
                self.stdout.write(self.style.SUCCESS(f"Published: {result.title} (v{result.version})"))
            else:
                raise CommandError(f"Publish failed: {result.message}")

        stats = apply_anchor_submissions(uc)
        self.stdout.write(self.style.SUCCESS(
            f"Anchors: {stats.captured} captured, {stats.outside} outside boundary, "
            f"{stats.skipped} skipped, {len(stats.errors)} error(s)."
        ))
        for err in stats.errors:
            self.stdout.write(self.style.WARNING(f"  {err}"))
