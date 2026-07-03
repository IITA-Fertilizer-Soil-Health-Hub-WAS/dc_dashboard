# Renames the RBAC models to match the "project everywhere" naming: a use case
# *is* a project, so UseCaseMembership → ProjectMembership and
# UseCaseAccessRequest → ProjectAccessRequest. RenameModel renames the default
# tables and rewrites FK references; related_names and the explicitly-named
# constraints are unchanged, so nothing else moves.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("rbac", "0008_alter_usecasemembership_options"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="UseCaseMembership",
            new_name="ProjectMembership",
        ),
        migrations.RenameModel(
            old_name="UseCaseAccessRequest",
            new_name="ProjectAccessRequest",
        ),
    ]
