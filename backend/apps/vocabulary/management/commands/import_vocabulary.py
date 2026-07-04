"""Import the Terminag controlled vocabulary into the DB.

    # from the configured GitHub repo (settings.TERMINAG_REPO_URL), shallow-cloned
    python manage.py import_vocabulary

    # from an existing local checkout (no network)
    python manage.py import_vocabulary --path /path/to/terminag

The repo layout is ``variables/*.csv`` + ``values/*.csv`` (see apps.vocabulary
.importer). Re-running is safe — rows are upserted.
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.vocabulary.importer import (
    VocabularySyncError,
    import_from_dir,
    sync_from_repo,
)


class Command(BaseCommand):
    help = "Import the Terminag controlled vocabulary (variables + values)."

    def add_arguments(self, parser):
        parser.add_argument("--path", help="Local checkout of the vocabulary repo "
                                           "(skips cloning).")
        parser.add_argument("--repo", help="Override the git repo URL to clone.")

    def handle(self, *args, **opts):
        if opts.get("path"):
            root = Path(opts["path"])
            if not (root / "variables").is_dir():
                raise CommandError(f"{root} has no variables/ folder — not a Terminag checkout.")
            report = import_from_dir(root)
        else:
            repo = opts.get("repo") or getattr(settings, "TERMINAG_REPO_URL", "")
            self.stdout.write(f"Cloning {repo} …")
            try:
                report = sync_from_repo(repo)
            except VocabularySyncError as exc:
                raise CommandError(str(exc))
        self.stdout.write(self.style.SUCCESS(
            f"Imported {report.variables} variables and {report.values} values "
            f"from {len(report.tables)} tables."))
