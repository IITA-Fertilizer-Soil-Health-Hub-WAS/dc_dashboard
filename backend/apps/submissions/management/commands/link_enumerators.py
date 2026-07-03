"""Bulk-link Enumerators to platform accounts (CLI).

Dry-run by default — prints the proposed links. Pass --apply to persist. After
applying, the next sync stamps Submission.collected_by for the linked collectors.

    python manage.py link_enumerators                     # preview all
    python manage.py link_enumerators --project SNS-RWANDA --apply
    python manage.py link_enumerators --by phone --apply   # phone only
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.projects.models import Project
from apps.submissions.linking import MATCH_KEYS, link_enumerators


class Command(BaseCommand):
    help = "Link Enumerators to User accounts by phone/name so collected_by populates."

    def add_arguments(self, parser):
        parser.add_argument("--project", dest="project", help="Limit to one Project code.")
        parser.add_argument(
            "--by", default=",".join(MATCH_KEYS),
            help="Comma-separated match keys in priority order (phone,name).",
        )
        parser.add_argument(
            "--apply", action="store_true",
            help="Persist the links. Without this it is a dry-run preview.",
        )
        parser.add_argument(
            "--overwrite", action="store_true",
            help="Re-link enumerators that already have a linked account.",
        )

    def handle(self, *args, **options):
        project = None
        if options["project"]:
            project = Project.objects.filter(code=options["project"]).first()
            if project is None:
                raise CommandError(f"Unknown project: {options['project']}")

        keys = tuple(k.strip() for k in options["by"].split(",") if k.strip())
        unknown = set(keys) - set(MATCH_KEYS)
        if unknown:
            raise CommandError(f"Unknown match key(s): {', '.join(sorted(unknown))}")

        report = link_enumerators(
            project=project, by=keys, overwrite=options["overwrite"],
            apply=options["apply"],
        )

        for p in report.actionable:
            if p.status == "match":
                self.stdout.write(
                    f"  {p.project}:{p.enid}  ->  {p.user_id} <{p.user_email}>  ({p.reason})"
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f"  {p.project}:{p.enid}  ->  AMBIGUOUS ({p.reason})")
                )

        verb = "Linked" if report.applied else "Would link"
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {report.matched} · ambiguous {report.ambiguous} · "
            f"unmatched {report.unmatched} · already linked {report.already}"
        ))
        if not report.applied and report.matched:
            self.stdout.write("Re-run with --apply to persist these links.")
