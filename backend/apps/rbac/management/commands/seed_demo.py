"""Seed a couple of use cases + users + memberships for manual exploration.

    python manage.py seed_demo

Creates an admin and one user per non-admin role, scoped to SNS-RWANDA, so you
can log into /admin and see per-use-case RBAC in action. Idempotent.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.rbac.models import Role, UseCaseMembership
from apps.usecases.models import Project

User = get_user_model()

DEMO_PASSWORD = "demo-pass-12345"


class Command(BaseCommand):
    help = "Seed demo use cases, users and memberships."

    def handle(self, *args, **options):
        rwanda, _ = Project.objects.get_or_create(
            code="SNS-RWANDA",
            defaults={"name": "SNS Rwanda", "countries": ["Rwanda"],
                      "enid_patterns": ["^RSENRW"], "hhid_patterns": ["^RSHHRW"]},
        )
        kalro, _ = Project.objects.get_or_create(
            code="KALRO", defaults={"name": "KALRO", "countries": ["Kenya"]}
        )

        admin, created = User.objects.get_or_create(
            email="admin@fieldbase.local",
            defaults={"is_staff": True, "is_superuser": True, "is_active": True,
                      "email_verified": True, "full_name": "Platform Admin"},
        )
        if created:
            admin.set_password(DEMO_PASSWORD)
            admin.save()

        role_users = {
            Role.COUNTRY_COORDINATOR: "country-coordinator@fieldbase.local",
            Role.TRIAL_COORDINATOR: "coordinator@fieldbase.local",
            Role.VIEWER: "viewer@fieldbase.local",
        }
        for role, email in role_users.items():
            user, created = User.objects.get_or_create(
                email=email,
                defaults={"is_active": True, "email_verified": True, "full_name": role.label},
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save()
            UseCaseMembership.objects.get_or_create(
                user=user, project=rwanda, role=role, defaults={"granted_by": admin}
            )

        self.stdout.write(self.style.SUCCESS(
            f"Seeded use cases [{rwanda.code}, {kalro.code}] and users "
            f"(password='{DEMO_PASSWORD}'): admin@fieldbase.local, coordinator@fieldbase.local, "
            f"agronomist@fieldbase.local, viewer@fieldbase.local"
        ))
