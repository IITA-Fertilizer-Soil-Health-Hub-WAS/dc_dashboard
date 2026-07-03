"""Hash a project's photo/media bytes so the PHOTO_REUSE integrity check can run.

    manage.py hash_media PROJ-A                 # only submissions not yet hashed
    manage.py hash_media PROJ-A --limit 200     # cap the batch (network-bound)
    manage.py hash_media PROJ-A --all           # re-hash everything
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.media_hash import hash_project_media
from apps.projects.models import Project


class Command(BaseCommand):
    help = "Compute SHA-256 hashes of submission media for a project."

    def add_arguments(self, parser):
        parser.add_argument("project", help="Project code")
        parser.add_argument("--limit", type=int, default=None, help="Max submissions to process")
        parser.add_argument("--all", action="store_true", help="Re-hash already-hashed submissions")

    def handle(self, *args, **opts):
        try:
            uc = Project.objects.get(code=opts["project"])
        except Project.DoesNotExist as e:
            raise CommandError(f"No use case with code {opts['project']!r}") from e

        stats = hash_project_media(uc, limit=opts["limit"], only_new=not opts["all"])
        self.stdout.write(self.style.SUCCESS(
            f"Hashed {stats.processed} submission(s); {stats.with_media} carried media."
        ))
