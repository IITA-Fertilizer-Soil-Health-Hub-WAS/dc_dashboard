# Broaden the owner backfill (0017 only looked at project-level coordinators):
# for projects still owner-less, follow the scope cascade — a coordinator over the
# project's country, then its region — and adopt them as owner. Most specific wins.
# Projects with no coordinator anywhere in their scope keep a null owner.
from django.db import migrations

_COORDINATOR_ROLES = [
    "TRIAL_COORDINATOR", "COUNTRY_COORDINATOR", "REGIONAL_COORDINATOR", "PLATFORM_ADMIN",
]


def _first_coordinator(Membership, **scope):
    m = (
        Membership.objects
        .filter(role__in=_COORDINATOR_ROLES, **scope)
        .order_by("created_at")
        .first()
    )
    return m.user_id if m and m.user_id else None


def backfill_owner_cascade(apps, schema_editor):
    Project = apps.get_model("projects", "Project")
    Membership = apps.get_model("rbac", "Membership")
    for project in Project.objects.filter(owner__isnull=True).select_related("country"):
        owner_id = None
        if project.country_id:
            owner_id = _first_coordinator(Membership, country_id=project.country_id)
            if owner_id is None and project.country.region_id:
                owner_id = _first_coordinator(Membership, region_id=project.country.region_id)
        if owner_id:
            project.owner_id = owner_id
            project.save(update_fields=["owner"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0017_backfill_project_owner"),
        ("rbac", "0010_rename_projectmembership_to_membership"),
    ]

    operations = [
        migrations.RunPython(backfill_owner_cascade, noop),
    ]
