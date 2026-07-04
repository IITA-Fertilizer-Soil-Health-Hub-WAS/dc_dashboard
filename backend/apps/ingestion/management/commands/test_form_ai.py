"""Verify the AI form-drafting integration end to end (Tier 3).

    python manage.py test_form_ai            # tiny live round-trip: is the key valid?
    python manage.py test_form_ai --draft    # also draft a form from a sample protocol

Use this to confirm FORM_AI_API_KEY / FORM_AI_MODEL work against the live
Anthropic API before enabling AI drafting for coordinators. Prints a clear pass
/ fail — it never publishes anything.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

SAMPLE = (
    "Household baseline. Record the farmer's full name. Record the primary crop "
    "grown (maize, beans, or cassava). Record plot area in hectares (0 to 50). "
    "Record the GPS location of the plot."
)


class Command(BaseCommand):
    help = "Check the AI form-drafting integration (key, model, and optionally a draft)."

    def add_arguments(self, parser):
        parser.add_argument("--draft", action="store_true",
                            help="Also draft a form from a built-in sample protocol.")

    def handle(self, *args, **opts):
        from apps.ingestion import form_ai

        result = form_ai.check()
        style = self.style.SUCCESS if result["ok"] else self.style.ERROR
        self.stdout.write(style(f"Connection: {result['message']}"))
        if result.get("model"):
            self.stdout.write(f"Model: {result['model']}")
        if not result["ok"] or not opts["draft"]:
            return

        self.stdout.write("\nDrafting from a sample protocol …")
        try:
            spec = form_ai.draft_spec(SAMPLE)
        except form_ai.FormAIError as exc:
            self.stdout.write(self.style.ERROR(f"Draft failed: {exc}"))
            return
        qs = spec.get("questions", [])
        self.stdout.write(self.style.SUCCESS(f"Drafted {len(qs)} question(s):"))
        for q in qs:
            self.stdout.write(f"  · {q.get('type'):14} {q.get('name'):20} {q.get('label','')}")
