"""Import the Terminag controlled vocabulary into the DB.

    # from the configured GitHub repo (settings.TERMINAG_REPO_URL), shallow-cloned
    python manage.py import_vocabulary

    # from an existing local checkout (no network)
    python manage.py import_vocabulary --path /path/to/terminag

The repo layout is ``variables/*.csv`` + ``values/*.csv`` (see apps.vocabulary
.importer). Re-running is safe — rows are upserted.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.vocabulary.importer import import_from_dir


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
            self._import(root)
            return

        repo = opts.get("repo") or getattr(settings, "TERMINAG_REPO_URL", "")
        if not repo:
            raise CommandError("No --path and no settings.TERMINAG_REPO_URL to clone from.")
        with tempfile.TemporaryDirectory() as tmp:
            self.stdout.write(f"Cloning {repo} …")
            try:
                subprocess.run(["git", "clone", "--depth", "1", repo, tmp],
                               check=True, capture_output=True, text=True)
            except (subprocess.CalledProcessError, FileNotFoundError) as exc:
                raise CommandError(f"Clone failed: {getattr(exc, 'stderr', exc)}")
            self._import(Path(tmp))

    def _import(self, root: Path):
        report = import_from_dir(root)
        self.stdout.write(self.style.SUCCESS(
            f"Imported {report.variables} variables and {report.values} values "
            f"from {len(report.tables)} tables."))
