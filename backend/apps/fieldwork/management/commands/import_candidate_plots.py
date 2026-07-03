"""Import GIS candidate plots (GeoJSON) for a use case.

    python manage.py import_candidate_plots SNS-RWANDA path/to/candidates.geojson
    python manage.py import_candidate_plots SNS-RWANDA plots.geojson --trial-prop area_id
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from apps.fieldwork.candidate_import import import_candidates
from apps.usecases.models import Project


class Command(BaseCommand):
    help = "Import GIS-proposed candidate plots (GeoJSON FeatureCollection) for a use case."

    def add_arguments(self, parser):
        parser.add_argument("code", help="Use case code")
        parser.add_argument("geojson", help="Path to a GeoJSON FeatureCollection")
        parser.add_argument("--trial-prop", default=None,
                            help="Property name carrying the trial key (else auto-detect)")

    def handle(self, *args, **options):
        try:
            uc = Project.objects.get(code=options["code"])
        except Project.DoesNotExist:
            raise CommandError(f"Unknown use case: {options['code']}") from None
        try:
            with open(options["geojson"], encoding="utf-8") as fh:
                geojson = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"Could not read GeoJSON: {exc}") from None

        stats = import_candidates(uc, geojson, trial_prop=options["trial_prop"])
        self.stdout.write(self.style.SUCCESS(
            f"{uc.code}: +{stats.created} new, ~{stats.updated} updated, "
            f"{stats.skipped} skipped across {stats.trials} trial(s)."
        ))
        for err in stats.errors[:20]:
            self.stdout.write(self.style.WARNING(f"  · {err}"))
