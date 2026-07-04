"""Database-per-tenant routing — OPT-IN foundation.

When ``settings.TENANT_DB_ROUTING`` is on, each request's tenant-scoped data
(submissions, review, validation, fieldwork, kpi) is read/written in that
institution's own database — resolved from its ``database_alias`` (a DATABASES
entry) or ``database_url`` (a full connection string it grants us). Shared tables
(accounts, rbac, institutions/projects config) always stay in the default DB.

Default deployments leave TENANT_DB_ROUTING off, so every method here is a no-op
and all data lives in the one shared database — nothing changes.

Not yet productionised: cross-database relations (a tenant's Submission → the
shared Project) can't be JOINed at the DB level, and each tenant DB must be
migrated (``manage.py migrate_tenant <code>``). Treat this as the wiring, not the
finished DB-per-tenant story.
"""
from __future__ import annotations

import threading

from django.conf import settings
from django.db import connections

# Apps whose data is per-tenant. Everything else is shared (default DB).
TENANT_APPS: set[str] = {"submissions", "review", "validation", "fieldwork", "kpi"}

_state = threading.local()


def set_active_tenant(alias: str | None) -> None:
    _state.alias = alias


def get_active_tenant() -> str | None:
    return getattr(_state, "alias", None)


def routing_enabled() -> bool:
    return bool(getattr(settings, "TENANT_DB_ROUTING", False))


def ensure_tenant_connection(org) -> str | None:
    """Return the DB alias to use for ``org``'s data, registering a connection
    from its database_url if needed. None → the shared default database."""
    if org is None:
        return None
    url = (getattr(org, "database_url", "") or "").strip()
    alias = (getattr(org, "database_alias", "") or "").strip()
    if url:
        conn_alias = f"tenant_{org.code}"
        if conn_alias not in connections.databases:
            import environ

            cfg = environ.Env.db_url_config(url)
            # Fill the per-connection defaults Django expects (db_url_config only
            # returns ENGINE/NAME/USER/…); otherwise code reading the raw config
            # (e.g. ATOMIC_REQUESTS) blows up.
            cfg.setdefault("ATOMIC_REQUESTS", False)
            cfg.setdefault("AUTOCOMMIT", True)
            cfg.setdefault("CONN_MAX_AGE", 0)
            cfg.setdefault("CONN_HEALTH_CHECKS", False)
            cfg.setdefault("OPTIONS", {})
            cfg.setdefault("TIME_ZONE", None)
            cfg.setdefault("TEST", {})
            for key in ("NAME", "USER", "PASSWORD", "HOST", "PORT"):
                cfg.setdefault(key, "")
            connections.databases[conn_alias] = cfg
        return conn_alias
    if alias and alias != "default":
        return alias if alias in connections.databases else None
    return None


class TenantRouter:
    """Routes tenant-app models to the active tenant DB; no-op when disabled."""

    def _target(self, model) -> str | None:
        if not routing_enabled():
            return None
        if model._meta.app_label not in TENANT_APPS:
            return None
        return get_active_tenant()  # alias, or None → default

    def db_for_read(self, model, **hints):
        return self._target(model)

    def db_for_write(self, model, **hints):
        return self._target(model)

    def allow_relation(self, obj1, obj2, **hints):
        return True  # relations across the shared/tenant split are allowed

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if not routing_enabled() or db == "default":
            return None  # default DB holds everything (Django's default behaviour)
        return app_label in TENANT_APPS  # a tenant DB only carries tenant apps


class TenantDBMiddleware:
    """Bind the request's tenant DB for the duration of the request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not routing_enabled():
            return self.get_response(request)
        alias = None
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and getattr(user, "organization_id", None):
            alias = ensure_tenant_connection(user.organization)
        set_active_tenant(alias)
        try:
            return self.get_response(request)
        finally:
            set_active_tenant(None)
