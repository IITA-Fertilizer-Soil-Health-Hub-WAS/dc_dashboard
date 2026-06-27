"""Field-work helpers."""
from __future__ import annotations

from django.db.models import Q


def project_enumerators(use_case):
    """Active users holding the Enumerator role on a project (incl. the
    country/region cascade) — the pool a coordinator assigns units to."""
    from apps.accounts.models import User
    from apps.rbac.models import Role

    covers = Q(memberships__use_case=use_case)
    if use_case.country_id:
        covers |= Q(memberships__country_id=use_case.country_id)
        if use_case.country.region_id:
            covers |= Q(memberships__region_id=use_case.country.region_id)
    return (
        User.objects.filter(Q(memberships__role=Role.ENUMERATOR) & covers, is_active=True)
        .distinct()
        .order_by("email")
    )
