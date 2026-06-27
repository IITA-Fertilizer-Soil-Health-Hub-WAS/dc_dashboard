"""Backfill Submission.lat/lon from the stored raw payload's _geolocation, so
existing submissions appear on the map without a re-sync."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import migrations


def _num(v):
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def backfill(apps, schema_editor):
    Submission = apps.get_model("submissions", "Submission")
    updated = []
    qs = Submission.objects.filter(lat__isnull=True).only("id", "raw_payload")
    for sub in qs.iterator(chunk_size=1000):
        geo = (sub.raw_payload or {}).get("_geolocation")
        if isinstance(geo, (list, tuple)) and len(geo) >= 2:
            lat, lon = _num(geo[0]), _num(geo[1])
            if lat is not None and lon is not None:
                sub.lat, sub.lon = lat, lon
                updated.append(sub)
        if len(updated) >= 1000:
            Submission.objects.bulk_update(updated, ["lat", "lon"])
            updated = []
    if updated:
        Submission.objects.bulk_update(updated, ["lat", "lon"])


class Migration(migrations.Migration):
    dependencies = [("submissions", "0005_submission_lat_submission_lon")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
