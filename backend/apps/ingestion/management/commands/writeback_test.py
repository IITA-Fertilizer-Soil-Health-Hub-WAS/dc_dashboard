"""Safely test write-back against a (sandbox) submission.

By default it is a DRY RUN: it fetches the original instance XML from the source,
applies the submission's reviewer edits, and prints the resulting edited XML —
WITHOUT submitting anything. Pass --commit to actually re-submit the edit (this
mutates the live record and requires WRITEBACK_ENABLED=true).

    python manage.py writeback_test <submission_uuid_or_ona_uuid>
    python manage.py writeback_test <id> --commit      # really write back

Always validate with a DRY RUN against a sandbox form before --commit.
"""
from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.backends.odk import OdkBackend, build_edited_instance
from apps.ingestion.backends.registry import get_backend_for
from apps.ingestion.writeback import collect_changes, push_submission
from apps.submissions.models import Submission


class Command(BaseCommand):
    help = "Dry-run (or --commit) write-back of a submission's edits to its source."

    def add_arguments(self, parser):
        parser.add_argument("submission", help="Submission UUID or ONA uuid")
        parser.add_argument("--commit", action="store_true",
                            help="Actually submit the edit (mutates the live record)")

    def _find(self, ref) -> Submission:
        sub = Submission.objects.filter(pk=ref).first() if "-" in ref else None
        sub = sub or Submission.objects.filter(ona_uuid=ref).first()
        if sub is None:
            raise CommandError(f"No submission matching {ref!r}")
        return sub

    def handle(self, *args, **options):
        sub = self._find(options["submission"])
        backend = get_backend_for(sub.use_case)
        changes = collect_changes(sub)

        self.stdout.write(f"Submission {sub.ona_uuid} ({sub.use_case.code}) via {backend.label}")
        self.stdout.write(f"Edited fields: {changes or '(none)'}")

        if not changes:
            self.stdout.write(self.style.WARNING("Nothing edited — nothing to write back."))
            return
        if not isinstance(backend, OdkBackend):
            self.stdout.write(self.style.WARNING(f"{backend.label} is not an ODK backend."))
            return

        if options["commit"]:
            if not getattr(settings, "WRITEBACK_ENABLED", False):
                raise CommandError("WRITEBACK_ENABLED is false — refusing to commit.")
            self.stdout.write(self.style.WARNING("COMMIT: submitting edited instance to source…"))
            push_submission(sub)
            sub.refresh_from_db()
            style = self.style.SUCCESS if sub.writeback_status == "SENT" else self.style.ERROR
            self.stdout.write(style(f"{sub.writeback_status}: {sub.writeback_message}"))
            return

        # DRY RUN: fetch + build edited XML, print it, submit nothing.
        path_changes = backend._resolve_paths(sub, changes)
        if not path_changes:
            self.stdout.write(self.style.WARNING("No edited fields map to source paths."))
            return
        try:
            original = backend._fetch_instance_xml(sub.form.server_ref, sub.ona_submission_id)
        except Exception as exc:
            raise CommandError(f"Could not fetch original instance: {exc}") from exc
        edited, old_iid = build_edited_instance(original, path_changes)
        self.stdout.write(self.style.SUCCESS("\n--- DRY RUN: edited instance (NOT submitted) ---"))
        self.stdout.write(f"deprecatedID (old instanceID): {old_iid}")
        self.stdout.write(f"path changes: {path_changes}")
        self.stdout.write(edited)
        self.stdout.write(self.style.SUCCESS(
            "\nNo submission was sent. Re-run with --commit (and WRITEBACK_ENABLED=true) to write back."
        ))
