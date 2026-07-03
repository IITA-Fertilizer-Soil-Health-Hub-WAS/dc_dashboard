from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0012_rename_use_case_fields"),
        ("submissions", "0012_rename_use_case_field"),
        ("fieldwork", "0007_rename_use_case_field"),
        ("kpi", "0002_rename_use_case_field"),
        ("review", "0006_rename_use_case_field"),
        ("rbac", "0007_rename_use_case_field"),
        ("validation", "0007_rename_use_case_field"),
    ]
    operations = [migrations.RenameModel(old_name="UseCase", new_name="Project")]
