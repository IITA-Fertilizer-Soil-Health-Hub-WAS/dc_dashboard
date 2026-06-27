"""Bulk-link Enumerators to platform User accounts.

During the ONA era, submissions arrive with an ENID but no platform UserID. To
make historical data trace to a registered account — so ``Submission.collected_by``
populates on the next sync — we match each Enumerator to a User by shared phone
number or name, and set ``Enumerator.user``.

Matching is deliberately conservative: a link is proposed only when exactly one
User matches. Multiple matches are reported as *ambiguous* for a human to resolve
rather than guessed. Run as a dry-run first (the default everywhere) to preview.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from apps.accounts.models import User

from .models import Enumerator

MATCH_KEYS = ("phone", "name")  # default priority order


def _norm_phone(value: str | None) -> str | None:
    """Last 9 digits, ignoring formatting and country-code variance."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) >= 9:
        return digits[-9:]
    return digits or None


def _norm_name(value: str | None) -> str | None:
    return re.sub(r"\s+", " ", (value or "").strip().lower()) or None


@dataclass
class Proposal:
    enumerator_pk: str
    enid: str
    use_case: str
    status: str  # "match" | "ambiguous" | "unmatched" | "already"
    reason: str = ""  # which key matched: "phone" | "name"
    user_id: str | None = None  # platform UserID of the matched account
    user_email: str | None = None


@dataclass
class LinkReport:
    applied: bool = False
    matched: int = 0
    ambiguous: int = 0
    unmatched: int = 0
    already: int = 0
    proposals: list[Proposal] = field(default_factory=list)

    @property
    def actionable(self) -> list[Proposal]:
        """Proposals worth a human's attention: confident matches first, then ambiguous."""
        order = {"match": 0, "ambiguous": 1}
        return sorted(
            (p for p in self.proposals if p.status in order),
            key=lambda p: (order[p.status], p.use_case, p.enid),
        )


def _build_user_indexes() -> tuple[dict[str, list[User]], dict[str, list[User]]]:
    by_phone: dict[str, list[User]] = {}
    by_name: dict[str, list[User]] = {}
    for u in User.objects.only("id", "user_id", "email", "phone", "full_name"):
        ph = _norm_phone(u.phone)
        if ph:
            by_phone.setdefault(ph, []).append(u)
        nm = _norm_name(u.full_name)
        if nm:
            by_name.setdefault(nm, []).append(u)
    return by_phone, by_name


def _candidates(enum, by_phone, by_name, keys) -> tuple[list[User], str]:
    for key in keys:
        if key == "phone":
            ph = _norm_phone(enum.phone)
            if ph and ph in by_phone:
                return by_phone[ph], "phone"
        elif key == "name":
            nm = _norm_name(f"{enum.first_name} {enum.surname}")
            if nm and nm in by_name:
                return by_name[nm], "name"
    return [], ""


def link_enumerators(
    *,
    use_case=None,
    use_cases=None,
    by: tuple[str, ...] = MATCH_KEYS,
    overwrite: bool = False,
    apply: bool = False,
) -> LinkReport:
    """Match Enumerators to Users and (optionally) persist the link.

    ``apply=False`` (default) previews without writing. ``overwrite=True``
    re-evaluates enumerators that already have a linked account. ``use_case``
    limits the scope to one project; ``use_cases`` (an iterable of UseCase or
    ids) limits it to a set — used to scope a coordinator to their own projects.
    """
    report = LinkReport(applied=apply)
    by_phone, by_name = _build_user_indexes()

    qs = Enumerator.objects.select_related("use_case")
    if use_case is not None:
        qs = qs.filter(use_case=use_case)
    if use_cases is not None:
        qs = qs.filter(use_case__in=list(use_cases))

    for enum in qs:
        base = dict(enumerator_pk=str(enum.pk), enid=enum.enid, use_case=enum.use_case.code)
        if enum.user_id and not overwrite:
            report.already += 1
            report.proposals.append(Proposal(status="already", **base))
            continue

        cands, reason = _candidates(enum, by_phone, by_name, by)
        uniq = list({u.pk: u for u in cands}.values())

        if len(uniq) == 1:
            user = uniq[0]
            report.matched += 1
            if apply:
                enum.user = user
                enum.save(update_fields=["user", "updated_at"])
            report.proposals.append(
                Proposal(status="match", reason=reason, user_id=user.user_id,
                         user_email=user.email, **base)
            )
        elif len(uniq) > 1:
            report.ambiguous += 1
            report.proposals.append(Proposal(status="ambiguous", reason=reason, **base))
        else:
            report.unmatched += 1
            report.proposals.append(Proposal(status="unmatched", **base))

    return report
