"""Event-completion status — the data-driven replacement for support_fun.R
`dynamic_colorcodeS`. Shared by the DATE_WINDOW validation rule (to flag overdue
events) and the dashboard event-completion grid (to colour cells).

Colours match the R app exactly:
  complete  #55b047 (green)   submitted
  due       #fdb415 (amber)   not yet submitted, still within window
  overdue   #c3531f (red)     not submitted, past target date
  future    #BE93D4 (purple)  anchor not reached yet (e.g. before site selection)
"""
from __future__ import annotations

from datetime import date, timedelta

COLORS = {
    "complete": "#55b047",
    "due": "#fdb415",
    "overdue": "#c3531f",
    "future": "#BE93D4",
    "na": "#ffffff",
}


def target_date(anchor_date: date | None, offset_days: int) -> date | None:
    if anchor_date is None:
        return None
    return anchor_date + timedelta(days=offset_days)


def event_status(
    *,
    event_date: date | None,
    anchor_date: date | None,
    offset_days: int,
    grace_days: int,
    today: date,
) -> str:
    """Return one of: complete / due / overdue / future / na."""
    if anchor_date is None:
        # The anchor (site selection / Event1) hasn't happened — future event.
        return "complete" if event_date else "future"

    target = anchor_date + timedelta(days=offset_days)
    if event_date is not None:
        return "complete"
    # Not submitted yet.
    if today > target + timedelta(days=grace_days):
        return "overdue"
    return "due"


def status_color(status: str) -> str:
    return COLORS.get(status, COLORS["na"])
