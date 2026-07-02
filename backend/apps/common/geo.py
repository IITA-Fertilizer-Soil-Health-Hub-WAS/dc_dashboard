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


def _point_in_ring(lat: float, lon: float, ring) -> bool:
    """Ray-casting test: is (lat, lon) inside this GeoJSON ring? Ring coords are
    [lon, lat]."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        try:
            xi, yi = float(ring[i][0]), float(ring[i][1])
            xj, yj = float(ring[j][0]), float(ring[j][1])
        except (TypeError, ValueError, IndexError):
            j = i
            continue
        if ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-15) + xi
        ):
            inside = not inside
        j = i
    return inside


def point_in_polygon(lat, lon, geometry) -> bool:
    """Is the point (lat, lon) inside a GeoJSON Polygon / MultiPolygon? Honours
    holes (a point in a hole is outside). Returns False on missing/invalid input —
    the caller treats "can't tell" as "not contained"."""
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    polys: list = []
    if isinstance(geometry, dict):
        gtype, coords = geometry.get("type"), geometry.get("coordinates")
        if gtype == "Polygon" and coords:
            polys = [coords]
        elif gtype == "MultiPolygon" and coords:
            polys = list(coords)
    for poly in polys:
        if not poly:
            continue
        if _point_in_ring(lat, lon, poly[0]):
            in_hole = any(_point_in_ring(lat, lon, hole) for hole in poly[1:])
            if not in_hole:
                return True
    return False
