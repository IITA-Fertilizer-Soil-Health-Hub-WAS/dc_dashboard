"""Retire the Domain Expert / Quality Check roles.

Coordinators are the reviewers (they hold the domain expertise), so any existing
membership granted as Survey Domain Expert or Quality Check is remapped to Trial
Coordinator — preserving review access for those people without the now-removed
roles.
"""
from __future__ import annotations

from django.db import migrations

RETIRED = ["SURVEY_DOMAIN_EXPERT", "QUALITY_CHECK"]


def remap_to_trial_coordinator(apps, schema_editor):
    UseCaseMembership = apps.get_model("rbac", "UseCaseMembership")
    for m in UseCaseMembership.objects.filter(role__in=RETIRED):
        # If the user already holds Trial Coordinator at this scope, drop the
        # duplicate; otherwise convert this row.
        exists = UseCaseMembership.objects.filter(
            user_id=m.user_id, role="TRIAL_COORDINATOR",
            use_case_id=m.use_case_id, country_id=m.country_id, region_id=m.region_id,
        ).exists()
        if exists:
            m.delete()
        else:
            m.role = "TRIAL_COORDINATOR"
            m.save(update_fields=["role"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("rbac", "0004_alter_usecasemembership_role"),
    ]

    operations = [migrations.RunPython(remap_to_trial_coordinator, noop)]
