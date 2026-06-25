"""Use-case scoping for dashboard views.

Every dashboard queryset is filtered to the use cases a user may view (their
memberships, or all for a Platform Admin) — the replacement for the R app's
`eia_apps ∩ active_use_case_list`. `get_scoped_use_case` 404s on anything the
user may not see, so URL tampering cannot cross use-case boundaries.
"""
from __future__ import annotations

from django.http import Http404

from apps.rbac.permissions import visible_use_cases


def get_scoped_use_case(request, code: str):
    uc = visible_use_cases(request.user).filter(code=code).first()
    if uc is None:
        raise Http404("Use case not found or not permitted")
    return uc
