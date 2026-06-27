"""Chart + map builders. The map is a Folium iframe; the submission trend is
returned as plain monthly counts and drawn server-side as CSS bars in the
template (no client JS), so it renders reliably inside HTMX-swapped tabs.
"""
from __future__ import annotations

from collections import Counter

import folium

AMBER = "#fdb415"
GREEN = "#55b047"
RED = "#c3531f"


def points_map_html(points) -> str:
    """Folium map from an iterable of points.

    Each point is a dict/tuple-like with ``lat``, ``lon``, ``label`` and an
    optional ``color`` (defaults to amber). Used by the M&E coverage and
    enumerator maps; ``trials_map_html`` is the household-specific variant.
    """
    pts = [p for p in points if p.get("lat") is not None and p.get("lon") is not None]
    if pts:
        center = (
            sum(float(p["lat"]) for p in pts) / len(pts),
            sum(float(p["lon"]) for p in pts) / len(pts),
        )
        zoom = 7
    else:
        center, zoom = (0.0, 20.0), 2
    m = folium.Map(location=center, zoom_start=zoom, tiles="OpenStreetMap")
    for p in pts:
        folium.CircleMarker(
            location=(float(p["lat"]), float(p["lon"])),
            radius=5,
            color=p.get("color", AMBER),
            fill=True,
            fill_opacity=0.85,
            weight=1,
            popup=p.get("label", ""),
        ).add_to(m)
    return m._repr_html_()


def _effective_date(s):
    """The day a submission counts towards: its field date, else the server
    submission time, else when we ingested it — matching the KPI aggregates so a
    submission always lands somewhere even when the form has no 'today' field."""
    if s.event_date:
        return s.event_date
    if getattr(s, "ona_submission_time", None):
        return s.ona_submission_time.date()
    if getattr(s, "ingested_at", None):
        return s.ingested_at.date()
    return None


def monthly_submission_counts(submissions) -> list[dict]:
    """Submissions per month (oldest→newest) by effective date, for the CSS bar
    trend. Returns [{'month': 'YYYY-MM', 'n': int}, …]."""
    counts: Counter[str] = Counter()
    for s in submissions:
        d = _effective_date(s)
        if d:
            counts[d.strftime("%Y-%m")] += 1
    return [{"month": m, "n": counts[m]} for m in sorted(counts)]


def trials_map_html(households) -> str:
    """Folium map of household/plot locations (was the leaflet 'Trials by Location')."""
    pts = [(float(h.lat), float(h.lon)) for h in households if h.lat is not None and h.lon is not None]
    if pts:
        center = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        zoom = 7
    else:
        center, zoom = (0.0, 20.0), 2
    m = folium.Map(location=center, zoom_start=zoom, tiles="OpenStreetMap")
    for h in households:
        if h.lat is None or h.lon is None:
            continue
        folium.CircleMarker(
            location=(float(h.lat), float(h.lon)),
            radius=5,
            color=AMBER,
            fill=True,
            fill_opacity=0.8,
            popup=f"{h.hhid}",
        ).add_to(m)
    return m._repr_html_()
