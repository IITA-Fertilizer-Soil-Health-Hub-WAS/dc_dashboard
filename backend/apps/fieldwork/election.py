"""Coordinator plot election.

For each trial, the country coordinator elects ONE candidate plot (a web decision,
later ground-truthed in the field). Electing promotes the chosen candidate to the
trial's authoritative CollectionUnit — the enumerator then registers the farmer
there, and submissions are spatially checked against it. See project memory:
plot-election governance.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.fieldwork.models import CandidatePlot, CollectionUnit


@dataclass
class TrialRow:
    trial_key: str
    candidates: list
    elected: object | None
    count: int

    @property
    def status(self) -> str:
        return "elected" if self.elected else "pending"


def trial_rows(use_case) -> list[TrialRow]:
    """One row per trial for the election queue: its candidates + which (if any) is
    elected. Ordered pending-first so the coordinator works the backlog."""
    by_trial: dict[str, list] = {}
    for c in use_case.candidate_plots.all():
        by_trial.setdefault(c.trial_key, []).append(c)
    rows = []
    for trial_key, cands in by_trial.items():
        elected = next((c for c in cands if c.status == CandidatePlot.Status.ELECTED), None)
        rows.append(TrialRow(trial_key=trial_key, candidates=cands,
                             elected=elected, count=len(cands)))
    rows.sort(key=lambda r: (r.elected is not None, r.trial_key))
    return rows


def election_progress(use_case) -> dict:
    rows = trial_rows(use_case)
    elected = sum(1 for r in rows if r.elected)
    return {"trials": len(rows), "elected": elected, "pending": len(rows) - elected}


@transaction.atomic
def elect_candidate(user, candidate: CandidatePlot, note: str = "") -> CollectionUnit:
    """Elect `candidate` for its trial: mark siblings not-selected, stamp the audit,
    and promote the chosen polygon to the trial's CollectionUnit (one per trial,
    reused on re-election). The unit's point is the candidate centroid for now —
    the field-captured farmer anchor overwrites it in the anchor-capture step."""
    uc = candidate.use_case
    siblings = CandidatePlot.objects.select_for_update().filter(
        use_case=uc, trial_key=candidate.trial_key
    )
    unit, _ = CollectionUnit.objects.update_or_create(
        use_case=uc, code=candidate.trial_key,
        defaults={
            "name": f"Trial {candidate.trial_key} · plot {candidate.candidate_ref}",
            "lat": candidate.centroid_lat,
            "lon": candidate.centroid_lon,
            "boundary": candidate.geometry,
            # Re-election resets the anchor — the elected outline changed.
            "anchor_captured": False,
            "anchor_captured_at": None,
            "anchor_captured_by": None,
            "attributes": {
                "elected_candidate": candidate.candidate_ref,
                "accessibility": candidate.accessibility,
                "cropping_region": candidate.cropping_region,
            },
        },
    )
    now = timezone.now()
    actor = user if getattr(user, "is_authenticated", False) else None
    for c in siblings:
        if c.pk == candidate.pk:
            c.status = CandidatePlot.Status.ELECTED
            c.elected_by = actor
            c.elected_at = now
            c.election_note = note
            c.collection_unit = unit
        else:
            c.status = CandidatePlot.Status.NOT_SELECTED
            c.collection_unit = None
            c.elected_by = None
            c.elected_at = None
        c.save(update_fields=["status", "elected_by", "elected_at", "election_note",
                              "collection_unit", "updated_at"])
    return unit


@transaction.atomic
def mark_no_valid_plot(user, use_case, trial_key: str, note: str = "") -> int:
    """Escape hatch: none of a trial's candidates is usable → mark them all
    not-selected (signals the GIS team). Returns how many were reset."""
    siblings = CandidatePlot.objects.select_for_update().filter(
        use_case=use_case, trial_key=trial_key
    )
    n = 0
    for c in siblings:
        c.status = CandidatePlot.Status.NOT_SELECTED
        c.collection_unit = None
        c.election_note = note
        c.save(update_fields=["status", "collection_unit", "election_note", "updated_at"])
        n += 1
    return n
