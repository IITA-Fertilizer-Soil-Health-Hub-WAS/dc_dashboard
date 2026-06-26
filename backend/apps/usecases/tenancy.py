"""Tenant-resolution helpers used when creating data that must belong to an org.

Keeps single-tenant (self-hosted) and multi-tenant (central) deployments working
from the same code: when no organization is named, fall back to the single
tenant if there is exactly one, else the conventional ``default`` org.
"""
from __future__ import annotations


def default_organization():
    """The organization to assign when none is specified, or None if ambiguous."""
    from .models import Organization

    orgs = Organization.objects.all()
    if orgs.count() == 1:
        return orgs.first()
    return orgs.filter(code="default").first()


def resolve_organization(code: str | None):
    """Resolve an org by code, falling back to the default tenant."""
    from .models import Organization

    if code:
        org = Organization.objects.filter(code=code).first()
        if org:
            return org
    return default_organization()
