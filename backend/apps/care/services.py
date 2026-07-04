"""Care caseload operations — assignment and referral (Phase 3)."""
from __future__ import annotations

from django.db import transaction

from .models import CareAssignment


@transaction.atomic
def assign_client(program, unit, worker, *, by=None, note=""):
    """Assign (or re-assign / refer) a client to a worker. Any current active
    assignment for the unit is deactivated first, preserving the referral chain,
    then a new active row is created. Returns the new assignment."""
    CareAssignment.objects.filter(unit=unit, is_active=True).update(is_active=False)
    return CareAssignment.objects.create(
        program=program, unit=unit, worker=worker, assigned_by=by, note=note, is_active=True,
    )


def worker_caseload(worker):
    """A worker's active assignments, newest first, with unit + programme loaded."""
    return (
        CareAssignment.objects.filter(worker=worker, is_active=True)
        .select_related("unit", "program", "program__project")
        .order_by("unit__code")
    )
