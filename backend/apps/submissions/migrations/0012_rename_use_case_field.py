from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("submissions", "0011_remove_submission_stage")]
    operations = [
        migrations.RenameField("enumerator", "use_case", "project"),
        migrations.RemoveConstraint("submission", "uq_submission_use_case_uuid"),
        migrations.RemoveIndex("submission", "submissions_use_cas_4bdd98_idx"),
        migrations.RemoveIndex("submission", "submissions_use_cas_0e12c8_idx"),
        migrations.RenameField("submission", "use_case", "project"),
        migrations.AddConstraint("submission", models.UniqueConstraint(
            fields=["project", "ona_uuid"], name="uq_submission_project_uuid")),
        migrations.AddIndex("submission", models.Index(
            fields=["project", "event_key"], name="submissions_project_evt_idx")),
        migrations.AddIndex("submission", models.Index(
            fields=["project", "enumerator"], name="submissions_project_enum_idx")),
    ]
