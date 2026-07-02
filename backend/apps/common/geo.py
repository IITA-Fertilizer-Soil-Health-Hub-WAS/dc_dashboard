"""Small geospatial helpers (no GIS dependency)."""
from __future__ import annotations

import math

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1, lon1, lat2, lon2) -> float | None:
    """Great-circle distance in metres between two lat/lon points, or None if any
    coordinate is missing/unparseable. Good to ~0.5% — ample for a "how far is this
    submission from its assigned plot?" QC check."""
    try:
        p1, l1, p2, l2 = (float(lat1), float(lon1), float(lat2), float(lon2))
    except (TypeError, ValueError):
        return None
    rp1, rp2 = math.radians(p1), math.radians(p2)
    dphi = math.radians(p2 - p1)
    dlambda = math.radians(l2 - l1)
    a = math.sin(dphi / 2) ** 2 + math.cos(rp1) * math.cos(rp2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _rings(geometry) -> list[list]:
    """The exterior coordinate rings of a GeoJSON Polygon / MultiPolygon."""
    if not isinstance(geometry, dict):
        return []
    gtype, coords = geometry.get("type"), geometry.get("coordinates")
    if gtype == "Polygon" and coords:
        return [coords[0]]
    if gtype == "MultiPolygon" and coords:
        return [poly[0] for poly in coords if poly]
    return []


def polygon_centroid(geometry) -> tuple[float, float] | None:
    """Approximate centroid (lat, lon) of a GeoJSON Polygon / MultiPolygon — the
    mean of its exterior ring vertices. Good enough to centre a map / seed a
    provisional reference point; not area-weighted. GeoJSON coords are [lon, lat].
    Returns None if there's no usable ring."""
    pts = [pt for ring in _rings(geometry) for pt in ring
           if isinstance(pt, (list, tuple)) and len(pt) >= 2]
    if not pts:
        return None
    try:
        lon = sum(float(p[0]) for p in pts) / len(pts)
        lat = sum(float(p[1]) for p in pts) / len(pts)
    except (TypeError, ValueError):
        return None
    return (lat, lon)
