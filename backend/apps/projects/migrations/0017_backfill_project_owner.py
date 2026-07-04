# Owner is now required when creating/editing a project. Backfill existing
# owner-less projects with a clear signal — a coordinator sitting directly on the
# project — so they aren't left owner-less. Projects with no such signal keep a
# null owner and get one assigned the next time they're edited in the console.
from django.db import migrations

_COORDINATOR_ROLES = [
    "TRIAL_COORDINATOR", "COUNTRY_COORDINATOR", "REGIONAL_COORDINATOR", "PLATFORM_ADMIN",
]


def backfill_owner(apps, schema_editor):
    Project = apps.get_model("projects", "Project")
    Membership = apps.get_model("rbac", "Membership")
    for project in Project.objects.filter(owner__isnull=True):
        membership = (
            Membership.objects
            .filter(project_id=project.id, role__in=_COORDINATOR_ROLES)
            .order_by("created_at")
            .first()
        )
        if membership and membership.user_id:
            project.owner_id = membership.user_id
            project.save(update_fields=["owner"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0016_project_owner"),
        ("rbac", "0010_rename_projectmembership_to_membership"),
    ]

    operations = [
        migrations.RunPython(backfill_owner, noop),
    ]
