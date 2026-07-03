"""The submission review state machine — one place defining legal transitions.

Each action declares the states it may fire from, the resulting state, and the
rbac action used to authorize it. Keeping this table central means the API, the
dashboards, and any future client all agree on the workflow.
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import ReviewAction, ReviewState


class TransitionError(Exception):
    """Raised when an action is not legal from the current state."""


class ReviewPermissionDenied(Exception):
    """Raised when the actor lacks the role to perform an action."""


@dataclass(frozen=True)
class Transition:
    from_states: frozenset[str]
    to_state: str
    permission: str  # rbac action passed to user_can()


S = ReviewState
A = ReviewAction

TRANSITIONS: dict[str, Transition] = {
    A.OPEN_REVIEW: Transition(
        frozenset({S.INGESTED, S.FLAGGED, S.EDIT_REQUESTED}), S.IN_REVIEW, "open_review"
    ),
    # Gate 2 (Regional) may send an endorsed submission back for more edits.
    A.REQUEST_EDIT: Transition(
        frozenset({S.IN_REVIEW, S.FLAGGED, S.INGESTED, S.QC_PENDING}),
        S.EDIT_REQUESTED,
        "request_edit",
    ),
    A.EDIT_VALUE: Transition(
        frozenset({S.IN_REVIEW, S.FLAGGED, S.INGESTED, S.EDIT_REQUESTED, S.EDITED}),
        S.EDITED,
        "edit",
    ),
    A.DECLINE: Transition(
        frozenset({S.IN_REVIEW, S.FLAGGED, S.INGESTED, S.EDIT_REQUESTED, S.EDITED, S.QC_PENDING}),
        S.DECLINED,
        "decline",
    ),
    # Gate 1 — Trial/Country Coordinator endorses; awaits Gate 2 validation.
    A.ENDORSE: Transition(
        frozenset({S.IN_REVIEW, S.EDITED, S.FLAGGED, S.INGESTED, S.EDIT_REQUESTED}),
        S.QC_PENDING,
        "endorse",
    ),
    # Gate 2 — only a Regional Coordinator gives the final validation, and only
    # on a submission that has cleared Gate 1 (QC_PENDING).
    A.QC_APPROVE: Transition(frozenset({S.QC_PENDING}), S.APPROVED, "final_approve"),
    A.REOPEN: Transition(
        frozenset({S.APPROVED, S.DECLINED, S.SUPERSEDED}), S.IN_REVIEW, "reopen"
    ),
    # System auto-flag from validation (INGESTED -> FLAGGED), no user permission.
    A.SYSTEM_FLAG: Transition(frozenset({S.INGESTED}), S.FLAGGED, None),
    # COMMENT does not change state; viewable by anyone who can view the project.
    A.COMMENT: Transition(frozenset(s for s in S.values), None, "view"),
    # SUPERSEDE is system-driven (raw re-ingested over an edit); no user perm.
    A.SUPERSEDE: Transition(frozenset(s for s in S.values), S.SUPERSEDED, None),
}


def legal_actions_from(state: str) -> list[str]:
    """Actions whose from_states include `state` (for rendering buttons)."""
    return [a for a, t in TRANSITIONS.items() if state in t.from_states]


def resolve(action: str, current_state: str) -> Transition:
    transition = TRANSITIONS.get(action)
    if transition is None:
        raise TransitionError(f"Unknown action: {action!r}")
    if current_state not in transition.from_states:
        raise TransitionError(
            f"Action {action} not allowed from state {current_state}"
        )
    return transition
