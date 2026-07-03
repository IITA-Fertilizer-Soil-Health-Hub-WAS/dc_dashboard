"""Idempotent Platform Admin bootstrap — safe to run on every deploy.

The two existing paths to a first admin are awkward for a container deploy:
`createsuperuser` is interactive (needs a shell), and the in-app "claim admin"
needs someone to sign in via Auth0 first. This command creates (or promotes) a
Platform Admin non-interactively from flags or env vars, and does NOTHING once an
admin already exists — so it can sit in the startup chain:

    python manage.py migrate && python manage.py bootstrap_admin && gunicorn ...

Credentials come from --email/--password or ADMIN_EMAIL/ADMIN_PASSWORD. If none is
set and there's no admin yet, it skips quietly (never fails startup). If the email
already belongs to a user (e.g. an Auth0 sign-in), that account is promoted rather
than duplicated.
"""
from __future__ import annotations

import os

from django.core.management.base import BaseCommand

from apps.accounts.services import platform_admin_exists


class Command(BaseCommand):
    help = "Create or promote the first Platform Admin, only if none exists yet."

    def add_arguments(self, parser):
        parser.add_argument("--email", default=os.environ.get("ADMIN_EMAIL"))
        parser.add_argument("--password", default=os.environ.get("ADMIN_PASSWORD"))

    def handle(self, *args, **opts):
        from apps.accounts.models import User

        if platform_admin_exists():
            self.stdout.write("A Platform Admin already exists — nothing to do.")
            return

        email = (opts.get("email") or "").strip().lower()
        password = opts.get("password") or ""
        if not email or not password:
            self.stdout.write(self.style.WARNING(
                "No Platform Admin, and no --email/--password (or ADMIN_EMAIL/"
                "ADMIN_PASSWORD) provided — skipping. Set those, or run "
                "'createsuperuser', or use the in-app 'Claim admin' after signing in."
            ))
            return

        existing = User.objects.filter(email__iexact=email).first()
        if existing is not None:
            existing.is_staff = True
            existing.is_superuser = True
            existing.is_active = True
            existing.email_verified = True
            existing.set_password(password)
            existing.save()
            self.stdout.write(self.style.SUCCESS(f"Promoted {email} to Platform Admin."))
            return

        User.objects.create_superuser(email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f"Created Platform Admin {email}."))
