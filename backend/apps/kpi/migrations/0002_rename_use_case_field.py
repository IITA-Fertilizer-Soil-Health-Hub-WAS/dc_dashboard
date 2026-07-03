from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("kpi", "0001_initial")]
    operations = [
        migrations.RenameField("enumeratorkpidaily", "use_case", "project"),
        migrations.RenameField("alertrule", "use_case", "project"),
        migrations.RenameField("alertevent", "use_case", "project"),
        migrations.RemoveIndex("projectkpidaily", "kpi_project_use_cas_309b03_idx"),
        migrations.RenameField("projectkpidaily", "use_case", "project"),
        migrations.AddIndex("projectkpidaily", models.Index(
            fields=["project", "date"], name="kpi_project_proj_date_idx")),
    ]
