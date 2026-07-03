from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("usecases", "0011_alter_usecase_options")]
    operations = [
        migrations.RemoveConstraint("formdefinition", "uniq_form_server_id"),
        migrations.RenameField("datasource", "use_case", "project"),
        migrations.RenameField("crop", "use_case", "project"),
        migrations.RenameField("trial", "use_case", "project"),
        migrations.RenameField("formdefinition", "use_case", "project"),
        migrations.RenameField("eventscheduleitem", "use_case", "project"),
        migrations.AddConstraint("formdefinition", models.UniqueConstraint(
            fields=["project", "server_form_id"],
            condition=models.Q(server_form_id__gt=""), name="uniq_form_server_id")),
    ]
