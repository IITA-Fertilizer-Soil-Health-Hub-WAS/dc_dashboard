from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("rbac", "0006_usecaseaccessrequest")]
    operations = [
        migrations.RemoveConstraint("usecasemembership", "membership_exactly_one_scope"),
        migrations.RemoveConstraint("usecasemembership", "uniq_membership_use_case"),
        migrations.RenameField("usecasemembership", "use_case", "project"),
        migrations.AddConstraint("usecasemembership", models.CheckConstraint(
            name="membership_exactly_one_scope",
            check=(
                Q(project__isnull=False, country__isnull=True, region__isnull=True)
                | Q(project__isnull=True, country__isnull=False, region__isnull=True)
                | Q(project__isnull=True, country__isnull=True, region__isnull=False)
            ))),
        migrations.AddConstraint("usecasemembership", models.UniqueConstraint(
            fields=["user", "project", "role"], condition=Q(project__isnull=False),
            name="uniq_membership_project")),
        migrations.RemoveConstraint("usecaseaccessrequest", "uniq_pending_access_request"),
        migrations.RenameField("usecaseaccessrequest", "use_case", "project"),
        migrations.AddConstraint("usecaseaccessrequest", models.UniqueConstraint(
            fields=["user", "project"], condition=Q(status="PENDING"),
            name="uniq_pending_access_request")),
    ]
