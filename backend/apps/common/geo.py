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
