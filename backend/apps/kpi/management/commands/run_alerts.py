"""Evaluate the M&E threshold-alert rules and notify watchers."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.kpi.alerts import run_alerts


class Command(BaseCommand):
    help = "Evaluate enabled AlertRules against current KPIs; log + email events."

    def handle(self, *args, **options):
        result = run_alerts()
        self.stdout.write(self.style.SUCCESS(
            f"Alerts evaluated: {result['events']} event(s), {result['emails']} email(s)."
        ))
