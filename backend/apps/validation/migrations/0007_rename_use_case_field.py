from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("validation", "0006_alter_validationrule_rule_type")]
    operations = [migrations.RenameField("validationrule", "use_case", "project")]
