"""Chart + map builders. The map is a Folium iframe; the submission trend is
returned as plain monthly counts and drawn server-side as CSS bars in the
template (no client JS), so it renders reliably inside HTMX-swapped tabs.
"""
from __future__ import annotations

from collections import Counter

import folium

AMBER = "#fdb415"
GREEN = "#55b047"
RED = "#b23b2e"


def candidate_plots_map_html(candidates, elected_id=None) -> str:
    """Map of a trial's candidate plot polygons for the election screen. The elected
    (or, absent one, the top-ranked) candidate is drawn in green; others in amber;
    not-selected in grey. Returns "" if no candidate has usable geometry."""
    from apps.common.geo import polygon_centroid

    drawn = []
    for c in candidates:
        centroid = polygon_centroid(c.geometry)
        if centroid:
            drawn.append((c, centroid))
    if not drawn:
        return ""
    center = (sum(p[1][0] for p in drawn) / len(drawn),
              sum(p[1][1] for p in drawn) / len(drawn))
    m = folium.Map(location=center, zoom_start=15, tiles="OpenStreetMap")
    for c, _ in drawn:
        if str(c.id) == str(elected_id) or c.status == "ELECTED":
            color = GREEN
        elif c.status == "NOT_SELECTED":
            color = "#888780"
        else:
            color = AMBER
        folium.GeoJson(
            {"type": "Feature", "geometry": c.geometry, "properties": {}},
            style_function=lambda _f, col=color: {
                "color": col, "weight": 2, "fillColor": col, "fillOpacity": 0.25},
            tooltip=f"Plot {c.candidate_ref} · rank {c.rank or '—'} · {c.accessibility or 'n/a'}",
        ).add_to(m)
    return m._repr_html_()


def submission_plot_map_html(submission) -> str:
    """A per-submission map: where it was collected (green) vs its assigned plot
    (amber), joined by a line, so a reviewer sees the GPS mismatch at a glance.
    Returns "" when there's nothing spatial to show."""
    sub_pt = None
    if submission.lat is not None and submission.lon is not None:
        sub_pt = (float(submission.lat), float(submission.lon))
    unit = submission.collection_unit
    unit_pt = None
    if unit is not None and unit.lat is not None and unit.lon is not None:
        unit_pt = (float(unit.lat), float(unit.lon))
    pts = [p for p in (sub_pt, unit_pt) if p]
    if not pts:
        return ""

    center = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    m = folium.Map(location=center, zoom_start=16 if len(pts) == 1 else 14,
                   tiles="OpenStreetMap")
    if unit_pt:
        folium.CircleMarker(unit_pt, radius=7, color=AMBER, fill=True, fill_opacity=0.9,
                            weight=1, popup=f"Assigned plot: {unit.code}").add_to(m)
    if sub_pt:
        folium.CircleMarker(sub_pt, radius=6, color=GREEN, fill=True, fill_opacity=0.9,
                            weight=1, popup="Collected here").add_to(m)
    if sub_pt and unit_pt:
        folium.PolyLine([sub_pt, unit_pt], color=RED, weight=2, dash_array="5").add_to(m)
        m.fit_bounds([sub_pt, unit_pt], padding=(40, 40))
    return m._repr_html_()


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


def trials_map_html(units) -> str:
    """Folium map of collection-unit (household / farm / plot) locations
    (was the leaflet 'Trials by Location')."""
    households = units
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
            popup=f"{h.code}",
        ).add_to(m)
    return m._repr_html_()
