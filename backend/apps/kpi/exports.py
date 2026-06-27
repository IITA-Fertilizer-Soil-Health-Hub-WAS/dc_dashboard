"""M&E data exports — KPI summary + enumerator performance (CSV) and a
collection-unit GeoJSON for GIS tools.

Deliberately dependency-light: CSV via the stdlib and GeoJSON via json, so no
pandas/openpyxl is pulled in. The authoritative approved dataset already has a
CSV export (dashboards.export_final); these add the M&E aggregates and the
spatial coverage layer. Binary formats (XLSX, SPSS/STATA) are an optional
follow-up that would need openpyxl / pyreadstat.
"""
from __future__ import annotations

import csv

from django.http import HttpResponse, JsonResponse

from .metrics import enumerator_metrics
from .models import ProjectKpiDaily


def _csv_response(use_case, suffix: str) -> HttpResponse:
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="{use_case.code.lower()}_{suffix}.csv"'
    )
    return response


def kpi_summary_csv(use_case) -> HttpResponse:
    """Daily KPI aggregates for the project (one row per collection day)."""
    response = _csv_response(use_case, "kpi_daily")
    writer = csv.writer(response)
    writer.writerow(["date", "submissions", "active_enumerators", "flags_opened"])
    for row in ProjectKpiDaily.objects.filter(use_case=use_case).order_by("date"):
        writer.writerow([row.date, row.submissions, row.active_enumerators, row.flags_opened])
    return response


def enumerator_csv(use_case, days: str = "all") -> HttpResponse:
    """Per-enumerator performance leaderboard."""
    response = _csv_response(use_case, "enumerators")
    writer = csv.writer(response)
    writer.writerow(["enid", "first_name", "surname", "submissions",
                     "approved", "approval_pct", "open_flags", "last_active"])
    for e in enumerator_metrics(use_case, days)["leaderboard"]:
        writer.writerow([
            e["enumerator__enid"], e["enumerator__first_name"] or "",
            e["enumerator__surname"] or "", e["n"], e["approved"],
            e["approval_pct"], e["open_flags"], e["last_active"] or "",
        ])
    return response


def units_geojson(use_case) -> JsonResponse:
    """Collection units as a GeoJSON FeatureCollection, each tagged with whether
    data has been received — drop straight into QGIS / Leaflet / kepler.gl."""
    from apps.fieldwork.models import CollectionUnit

    units = CollectionUnit.objects.filter(
        use_case=use_case, lat__isnull=False, lon__isnull=False
    )
    collected_ids = set(
        units.filter(submissions__isnull=False).values_list("id", flat=True)
    )
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(u.lon), float(u.lat)]},
            "properties": {
                "code": u.code,
                "name": u.name,
                "collected": u.id in collected_ids,
                "country": u.country,
                "region": u.region,
                "district": u.district,
            },
        }
        for u in units
    ]
    fc = {"type": "FeatureCollection", "features": features}
    response = JsonResponse(fc)
    response["Content-Disposition"] = (
        f'attachment; filename="{use_case.code.lower()}_units.geojson"'
    )
    return response


# Dispatch table: export kind → builder. `geojson` flags JSON handling in the view.
EXPORTS = {
    "kpi-summary": {"label": "KPI summary (CSV)", "builder": kpi_summary_csv},
    "enumerators": {"label": "Enumerator performance (CSV)", "builder": enumerator_csv},
    "units-geojson": {"label": "Collection units (GeoJSON)", "builder": units_geojson},
}


def build_export(kind: str, use_case):
    """Return an HttpResponse for the given export kind, or None if unknown."""
    spec = EXPORTS.get(kind)
    if spec is None:
        return None
    return spec["builder"](use_case)
