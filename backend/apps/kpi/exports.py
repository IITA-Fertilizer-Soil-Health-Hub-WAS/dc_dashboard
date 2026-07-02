"""M&E data exports.

Tabular datasets (KPI summary, enumerator performance, the approved dataset) are
each offered in several formats — CSV, XLSX, and the stats formats STATA (.dta)
and SPSS (.sav). The collection units also export as GeoJSON for GIS.

CSV/XLSX are always available (stdlib + openpyxl). The stats formats need
pandas + pyreadstat; if those aren't installed the export degrades to a clear
501 and the buttons are hidden, rather than 500-ing.
"""
from __future__ import annotations

import csv
import io
import tempfile

from django.http import HttpResponse, JsonResponse

from .metrics import enumerator_metrics
from .models import ProjectKpiDaily

# --- datasets: each returns (columns, rows) ---------------------------------

def kpi_summary_dataset(use_case, days: str = "all"):
    columns = ["date", "submissions", "active_enumerators", "flags_opened"]
    rows = [
        [str(r.date), r.submissions, r.active_enumerators, r.flags_opened]
        for r in ProjectKpiDaily.objects.filter(use_case=use_case).order_by("date")
    ]
    return columns, rows


def enumerator_dataset(use_case, days: str = "all"):
    columns = ["enid", "first_name", "surname", "submissions", "approved",
               "approval_pct", "open_flags", "last_active"]
    rows = [
        [e["enumerator__enid"], e["enumerator__first_name"] or "",
         e["enumerator__surname"] or "", e["n"], e["approved"],
         e["approval_pct"], e["open_flags"], str(e["last_active"] or "")]
        for e in enumerator_metrics(use_case, days)["leaderboard"]
    ]
    return columns, rows


def approved_dataset(use_case, days: str = "all"):
    """The clean, reviewed output — approved submissions with their authoritative
    (possibly edited) values. This is what analysts actually want."""
    from apps.dashboards.final import final_rows

    _subs, keys, rows = final_rows(use_case)
    base = ["ona_uuid", "ENID", "HHID", "collected_by", "event", "crop", "date", "state"]
    columns = base + [k for k in keys if k not in base]
    out = []
    for row in rows:
        s, values = row["submission"], row["values"]
        record = {
            "ona_uuid": s.ona_uuid,
            "ENID": s.enumerator.enid if s.enumerator else "",
            "HHID": s.collection_unit.code if s.collection_unit else "",
            "collected_by": s.collected_by.user_id if s.collected_by else "",
            "event": s.event_key,
            "crop": s.crop.name if s.crop else "",
            "date": str(s.event_date or ""),
            "state": "APPROVED",
            **{k: values.get(k, "") for k in keys},
        }
        out.append([record.get(c, "") for c in columns])
    return columns, out


DATASETS = {
    "kpi-summary": {"label": "KPI summary", "suffix": "kpi_daily",
                    "builder": kpi_summary_dataset},
    "enumerators": {"label": "Enumerator performance", "suffix": "enumerators",
                    "builder": enumerator_dataset},
    "approved": {"label": "Approved dataset", "suffix": "approved",
                 "builder": approved_dataset},
}


# --- format writers ---------------------------------------------------------

def _filename(use_case, suffix: str, ext: str) -> str:
    return f"{use_case.code.lower()}_{suffix}.{ext}"


def _csv_response(columns, rows, use_case, suffix) -> HttpResponse:
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="{_filename(use_case, suffix, "csv")}"'
    )
    writer = csv.writer(response)
    writer.writerow(columns)
    writer.writerows(rows)
    return response


def _xlsx_response(columns, rows, use_case, suffix) -> HttpResponse:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = suffix[:31]
    ws.append(columns)
    for row in rows:
        ws.append(["" if v is None else v for v in row])
    buf = io.BytesIO()
    wb.save(buf)
    response = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="{_filename(use_case, suffix, "xlsx")}"'
    )
    return response


def stats_available() -> bool:
    """True when pandas + pyreadstat are importable (STATA/SPSS exports)."""
    try:
        import pandas  # noqa: F401
        import pyreadstat  # noqa: F401
    except ImportError:
        return False
    return True


def _sanitize_columns(columns):
    """STATA/SPSS variable names must start with a letter and contain only
    [A-Za-z0-9_]. De-duplicate and clip to a safe length."""
    seen: dict[str, int] = {}
    out = []
    for col in columns:
        name = "".join(c if c.isalnum() else "_" for c in str(col)).strip("_")
        if not name or not name[0].isalpha():
            name = f"v_{name}" if name else "v"
        name = name[:30]
        if name in seen:
            seen[name] += 1
            name = f"{name[:27]}_{seen[name]}"
        else:
            seen[name] = 0
        out.append(name)
    return out


def _stats_response(columns, rows, use_case, suffix, ext) -> HttpResponse:
    import pandas as pd
    import pyreadstat

    safe_cols = _sanitize_columns(columns)
    # Everything as strings — robust across heterogeneous ODK values.
    df = pd.DataFrame(
        [["" if v is None else str(v) for v in row] for row in rows],
        columns=safe_cols,
    )
    writer = pyreadstat.write_dta if ext == "dta" else pyreadstat.write_sav
    content_type = ("application/x-stata-dta" if ext == "dta"
                    else "application/x-spss-sav")
    with tempfile.NamedTemporaryFile(suffix=f".{ext}") as tmp:
        writer(df, tmp.name)
        tmp.seek(0)
        data = tmp.read()
    response = HttpResponse(data, content_type=content_type)
    response["Content-Disposition"] = (
        f'attachment; filename="{_filename(use_case, suffix, ext)}"'
    )
    return response


FORMATS = {
    "csv": {"label": "CSV", "stats": False},
    "xlsx": {"label": "Excel", "stats": False},
    "dta": {"label": "STATA", "stats": True},
    "sav": {"label": "SPSS", "stats": True},
}


def render_dataset(kind: str, fmt: str, use_case, days: str = "all"):
    """Build a dataset and serialise it in the requested format. Returns an
    HttpResponse, or None for an unknown dataset/format, or a 501 response when
    a stats format is requested but pandas/pyreadstat are unavailable."""
    spec = DATASETS.get(kind)
    fmt_spec = FORMATS.get(fmt)
    if spec is None or fmt_spec is None:
        return None
    if fmt_spec["stats"] and not stats_available():
        return HttpResponse(
            "STATA/SPSS export needs pandas + pyreadstat, which are not installed.",
            status=501, content_type="text/plain",
        )
    columns, rows = spec["builder"](use_case, days)
    suffix = spec["suffix"]
    if fmt == "csv":
        return _csv_response(columns, rows, use_case, suffix)
    if fmt == "xlsx":
        return _xlsx_response(columns, rows, use_case, suffix)
    return _stats_response(columns, rows, use_case, suffix, fmt)


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
    response = JsonResponse({"type": "FeatureCollection", "features": features})
    response["Content-Disposition"] = (
        f'attachment; filename="{_filename(use_case, "units", "geojson")}"'
    )
    return response


def export_options() -> dict:
    """Datasets + the formats currently available, for the export UI."""
    formats = [
        {"fmt": f, **spec}
        for f, spec in FORMATS.items()
        if not spec["stats"] or stats_available()
    ]
    datasets = [{"kind": k, "label": v["label"]} for k, v in DATASETS.items()]
    return {"datasets": datasets, "formats": formats}
