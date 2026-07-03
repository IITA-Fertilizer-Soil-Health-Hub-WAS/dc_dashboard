# A membership grants a role at project OR country OR region scope, so the plain
# name "Membership" is more accurate than "ProjectMembership". (ProjectAccessRequest
# keeps its name — that model is project-only.) RenameModel renames the table;
# related_names and named constraints are unchanged.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("rbac", "0009_rename_usecase_models_to_project"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="ProjectMembership",
            new_name="Membership",
        ),
    ]
