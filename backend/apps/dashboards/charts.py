"""Chart + map builders (Plotly trend, Folium map) — parity with the R app's
plotly submission trend and leaflet trials map. Each returns an HTML fragment to
embed in a template.
"""
from __future__ import annotations

from collections import Counter

import folium
import plotly.graph_objects as go
from plotly.io import to_html

AMBER = "#fdb415"
GREEN = "#55b047"


def submission_trend_html(submissions) -> str:
    """Monthly submission count line chart (was 'Trend of Submissions')."""
    counts: Counter[str] = Counter()
    for s in submissions:
        if s.event_date:
            counts[s.event_date.strftime("%Y-%m")] += 1
    months = sorted(counts)
    fig = go.Figure(
        go.Scatter(
            x=months,
            y=[counts[m] for m in months],
            mode="lines+markers",
            line={"color": GREEN, "width": 2},
            marker={"color": AMBER, "size": 8},
        )
    )
    fig.update_layout(
        margin={"l": 40, "r": 20, "t": 30, "b": 40},
        height=320,
        xaxis_title="Month",
        yaxis_title="Submissions",
        template="plotly_white",
    )
    return to_html(fig, include_plotlyjs="cdn", full_html=False)


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
