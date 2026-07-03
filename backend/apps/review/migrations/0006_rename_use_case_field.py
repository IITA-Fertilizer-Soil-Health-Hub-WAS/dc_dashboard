from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("review", "0005_rejectionreason_review_rejection_reason")]
    operations = [migrations.RenameField("rejectionreason", "use_case", "project")]
