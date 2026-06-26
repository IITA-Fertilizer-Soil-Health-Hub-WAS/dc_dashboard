"""Migrate legacy Auth0 `eia_apps` access into per-use-case memberships.

The R app had no roles — Auth0 metadata `eia_apps` simply listed the use cases a
user could see. On first OIDC login we snapshot that claim into
`User.legacy_eia_apps`; this command turns each entry into a VIEWER membership.
Admins then upgrade specific users to Trial Coordinator.

    python manage.py migrate_eia_apps            # all users with a snapshot
    python manage.py migrate_eia_apps --email x  # one user
    python manage.py migrate_eia_apps --dry-run
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.rbac.models import Role, UseCaseMembership
from apps.usecases.models import UseCase

User = get_user_model()


class Command(BaseCommand):
    help = "Create VIEWER memberships from each user's legacy Auth0 eia_apps."

    def add_arguments(self, parser):
        parser.add_argument("--email", help="Limit to a single user")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        qs = User.objects.exclude(legacy_eia_apps={})
        if options["email"]:
            qs = qs.filter(email=options["email"])

        created = skipped = unknown = 0
        for user in qs:
            apps = user.legacy_eia_apps
            codes = apps.keys() if isinstance(apps, dict) else apps
            for code in codes:
                uc = UseCase.objects.filter(code=code).first()
                if uc is None:
                    unknown += 1
                    self.stderr.write(self.style.WARNING(f"  ? unknown use case '{code}' for {user.email}"))
                    continue
                exists = UseCaseMembership.objects.filter(
                    user=user, use_case=uc, role=Role.VIEWER
                ).exists()
                if exists:
                    skipped += 1
                    continue
                if not options["dry_run"]:
                    UseCaseMembership.objects.create(user=user, use_case=uc, role=Role.VIEWER)
                created += 1

        prefix = "[dry-run] " if options["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}{created} memberships created, {skipped} already existed, "
            f"{unknown} unknown use cases"
        ))
