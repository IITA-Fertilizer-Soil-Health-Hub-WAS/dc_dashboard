"""Bulk-load a project's collection units (plots / farmers-households) from CSV.

A coordinator plans field work by importing the units to collect on. The CSV
needs a ``code`` column (the unit id that submissions match on); ``name``,
``lat``, ``lon``, ``country``, ``region``, ``district`` are recognised, and any
other columns are kept on the unit's ``attributes``. Re-importing updates by code
(idempotent).
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from .models import CollectionUnit

KNOWN_COLUMNS = {"code", "name", "lat", "lon", "country", "region", "district"}


@dataclass
class ImportReport:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _num(value):
    value = (value or "").strip() if isinstance(value, str) else value
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def import_collection_units(project, csv_text: str) -> ImportReport:
    report = ImportReport()
    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames or "code" not in {(c or "").strip().lower() for c in reader.fieldnames}:
        report.errors.append("CSV must have a 'code' column.")
        return report

    # Normalise header lookup (case-insensitive).
    for raw in reader:
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        code = row.get("code", "")
        if not code:
            report.skipped += 1
            continue
        attrs = {k: v for k, v in row.items() if k not in KNOWN_COLUMNS and v}
        _, created = CollectionUnit.objects.update_or_create(
            project=project, code=code,
            defaults={
                "name": row.get("name", ""),
                "lat": _num(row.get("lat")),
                "lon": _num(row.get("lon")),
                "country": row.get("country", ""),
                "region": row.get("region", ""),
                "district": row.get("district", ""),
                "attributes": attrs,
            },
        )
        if created:
            report.created += 1
        else:
            report.updated += 1
    return report
