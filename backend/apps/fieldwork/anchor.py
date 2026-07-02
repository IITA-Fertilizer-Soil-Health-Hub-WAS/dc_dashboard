"""Capture the farmer-field anchor for an elected plot.

The country coordinator goes to the field and records the ONE point where the
trial actually sits inside the elected polygon (in production, the geopoint from a
coordinator-only ODK micro-form; the same service also backs an in-app capture).
Fieldbase gates it with the containment check, then freezes it onto the
CollectionUnit as the operative point every later submission is measured against.
See project memory: plot-election governance.
"""
from __future__ import annotations

from django.utils import timezone

from apps.common.geo import point_in_polygon


def capture_anchor(user, unit, lat, lon) -> tuple[bool, str]:
    """Freeze (lat, lon) as `unit`'s farmer-field anchor, if it falls inside the
    elected boundary. Returns (ok, message); on failure the unit is left unchanged."""
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False, "A valid latitude and longitude are required."
    if unit.boundary and not point_in_polygon(lat, lon, unit.boundary):
        return False, "That point is outside the elected plot — capture it inside the boundary."
    unit.lat = lat
    unit.lon = lon
    unit.anchor_captured = True
    unit.anchor_captured_at = timezone.now()
    unit.anchor_captured_by = user if getattr(user, "is_authenticated", False) else None
    unit.save(update_fields=[
        "lat", "lon", "anchor_captured", "anchor_captured_at", "anchor_captured_by",
        "updated_at",
    ])
    # The plot is now field-ready: ping any enumerators already assigned to it.
    try:
        from apps.fieldwork.notifications import notify_plot_ready

        notify_plot_ready(unit)
    except Exception:  # pragma: no cover - defensive
        pass
    return True, "Farmer-field anchor captured."
