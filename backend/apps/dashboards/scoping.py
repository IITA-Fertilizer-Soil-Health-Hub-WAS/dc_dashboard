"""Use-case scoping for dashboard views.

Every dashboard queryset is filtered to the use cases a user may view (their
memberships, or all for a Platform Admin) — the replacement for the R app's
`eia_apps ∩ active_project_list`. `get_scoped_project` 404s on anything the
user may not see, so URL tampering cannot cross use-case boundaries.
"""
from __future__ import annotations

from django.http import Http404

from apps.rbac.permissions import visible_projects


def get_scoped_project(request, code: str):
    uc = visible_projects(request.user).filter(code=code).first()
    if uc is None:
        raise Http404("Project not found or not permitted")
    return uc
