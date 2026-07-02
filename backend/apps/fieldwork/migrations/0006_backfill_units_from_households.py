"""Household → CollectionUnit merge, stage 2: backfill.

Mirror every Household onto a CollectionUnit (code = hhid), enriching the unit's
fields without ever overwriting a captured election anchor's coordinates. Then set
Submission.collection_unit for any submission that only carried a household, so the
two FKs agree before reads flip to the unit (stage 3).
"""
from __future__ import annotations

from django.db import migrations


def backfill(apps, schema_editor):
    Household = apps.get_model("submissions", "Household")
    CollectionUnit = apps.get_model("fieldwork", "CollectionUnit")
    Submission = apps.get_model("submissions", "Submission")

    unit_by: dict = {}  # (use_case_id, code) -> unit
    for hh in Household.objects.all().iterator():
        unit, _ = CollectionUnit.objects.get_or_create(
            use_case_id=hh.use_case_id, code=hh.hhid
        )
        changed = False
        if not unit.anchor_captured and unit.lat is None and hh.lat is not None:
            unit.lat, unit.lon = hh.lat, hh.lon
            changed = True
        if unit.enumerator_id is None and hh.enumerator_id:
            unit.enumerator_id = hh.enumerator_id
            changed = True
        if unit.alt is None and hh.alt is not None:
            unit.alt = hh.alt
            changed = True
        if not unit.country and hh.country:
            unit.country = hh.country
            changed = True
        if unit.site_selection_date is None and hh.site_selection_date:
            unit.site_selection_date = hh.site_selection_date
            changed = True
        if changed:
            unit.save()
        unit_by[(hh.use_case_id, hh.hhid)] = unit

    for sub in (
        Submission.objects.filter(household__isnull=False, collection_unit__isnull=True)
        .select_related("household").iterator()
    ):
        hh = sub.household
        unit = unit_by.get((hh.use_case_id, hh.hhid))
        if unit is None:
            unit, _ = CollectionUnit.objects.get_or_create(
                use_case_id=hh.use_case_id, code=hh.hhid
            )
        sub.collection_unit_id = unit.id
        sub.save(update_fields=["collection_unit"])


def noop(apps, schema_editor):
    """Irreversible data backfill — units/FKs stay populated on reverse."""


class Migration(migrations.Migration):
    dependencies = [
        ("fieldwork", "0005_collectionunit_alt_collectionunit_enumerator_and_more"),
        ("submissions", "0009_submission_media_hashed_at"),
    ]

    operations = [migrations.RunPython(backfill, noop)]
