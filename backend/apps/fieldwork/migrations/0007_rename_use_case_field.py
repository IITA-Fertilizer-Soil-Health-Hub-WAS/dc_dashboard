from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("fieldwork", "0006_backfill_units_from_households")]
    operations = [
        migrations.RenameField("collectionunit", "use_case", "project"),
        migrations.RenameField("job", "use_case", "project"),
        migrations.RemoveIndex("candidateplot", "fieldwork_c_use_cas_613427_idx"),
        migrations.RenameField("candidateplot", "use_case", "project"),
        migrations.AddIndex("candidateplot", models.Index(
            fields=["project", "trial_key"], name="fieldwork_cand_project_idx")),
    ]
