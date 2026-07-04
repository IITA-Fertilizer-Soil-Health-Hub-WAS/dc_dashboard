"""Provision collector accounts on the collection server for existing users.

The signals in ``apps.ingestion.signals`` provision going forward (on new users
and new grants). This command backfills what already exists and is the safe way
to *verify a live server* before flipping ``AUTO_PROVISION_COLLECTORS`` on:

    # dry-run: show what would be provisioned, touch no server
    python manage.py provision_collectors --project SNS-RWANDA --dry-run

    # provision every member of one project
    python manage.py provision_collectors --project SNS-RWANDA

    # provision one user across the projects they're a member of
    python manage.py provision_collectors --user jo@example.org

Provisioning is fail-soft: a per-account error is reported and recorded, the run
continues. Nothing here is gated by the setting — running the command IS the
opt-in — but it still only touches servers reachable via each project's
DataSource credentials.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.ingestion import provisioning
from apps.projects.models import Project
from apps.rbac.models import Membership


class Command(BaseCommand):
    help = "Create/link collector accounts on the collection server for existing users."

    def add_arguments(self, parser):
        parser.add_argument("--project", help="Project code: provision all its members.")
        parser.add_argument("--user", help="User email: provision across their projects.")
        parser.add_argument("--dry-run", action="store_true",
                            help="List (user, project) pairs without calling any server.")

    def handle(self, *args, **opts):
        pairs = self._pairs(opts)
        if not pairs:
            self.stdout.write("Nothing to provision.")
            return
        dry = opts["dry_run"]
        self.stdout.write(f"{'Would provision' if dry else 'Provisioning'} {len(pairs)} "
                          f"(user, project) pair(s)…")
        ok = failed = 0
        for user, project in pairs:
            if dry:
                self.stdout.write(f"  · {user.email} → {project.code}")
                continue
            acct = provisioning.provision_for_project(user, project)
            line = f"  {acct.status:11} {user.email} → {project.code}: {acct.message}"
            if acct.status == acct.Status.FAILED:
                failed += 1
                self.stderr.write(self.style.ERROR(line))
            else:
                ok += 1
                self.stdout.write(self.style.SUCCESS(line))
        if not dry:
            self.stdout.write(f"\nDone: {ok} ok, {failed} failed.")

    def _pairs(self, opts):
        if not (opts["project"] or opts["user"]):
            raise CommandError("Give --project <code> and/or --user <email>.")
        qs = Membership.objects.select_related("user", "project").filter(project__isnull=False)
        if opts["project"]:
            try:
                project = Project.objects.get(code=opts["project"])
            except Project.DoesNotExist:
                raise CommandError(f"No project with code {opts['project']!r}.")
            qs = qs.filter(project=project)
        if opts["user"]:
            qs = qs.filter(user__email=opts["user"])
        # Unique (user, project); a user may hold several roles on one project.
        seen, pairs = set(), []
        for m in qs:
            key = (m.user_id, m.project_id)
            if key in seen:
                continue
            seen.add(key)
            pairs.append((m.user, m.project))
        return pairs
