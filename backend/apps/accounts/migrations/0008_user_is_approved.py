# Split approval out of is_active. Add is_approved and backfill it True for every
# currently-active user (under the old model, is_active==approved), so nobody who
# already had access loses it. New Auth0 users will be is_active=True +
# is_approved=False (pending) going forward.
from django.db import migrations, models


def backfill_approved(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(is_active=True).update(is_approved=True)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_remove_userprofile_family_name_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="is_approved",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(backfill_approved, noop),
    ]
