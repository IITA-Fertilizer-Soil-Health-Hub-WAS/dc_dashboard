"""Backend registry — maps a backend type to its implementation.

Add a new collection tool by implementing CollectionBackend and registering it
here; the rest of the engine (ingestion, onboarding, write-back) is unchanged.
"""
from __future__ import annotations

from .base import CollectionBackend
from .kobo import KoboBackend
from .odkcentral import OdkCentralBackend
from .ona import OnaBackend

# Register backends here. Adding a new collection tool = one entry.
_BACKENDS: dict[str, type[CollectionBackend]] = {
    OnaBackend.type: OnaBackend,
    KoboBackend.type: KoboBackend,
    OdkCentralBackend.type: OdkCentralBackend,
}

# (value, label) choices for model fields / form selects.
BACKEND_CHOICES = [(t, cls.label) for t, cls in _BACKENDS.items()]
DEFAULT_BACKEND = OnaBackend.type


def backend_class(backend_type: str) -> type[CollectionBackend]:
    return _BACKENDS.get(backend_type, OnaBackend)


def build_backend(backend_type: str = DEFAULT_BACKEND, *, base_url: str = "",
                  token: str = "", config: dict | None = None) -> CollectionBackend:
    return backend_class(backend_type)(base_url=base_url, token=token, config=config)


def get_backend_for(project) -> CollectionBackend:
    """Resolve the backend bound to a project via its DataSource, or fall back
    to ONA configured from global settings (back-compat for existing projects)."""
    ds = getattr(project, "data_source", None)
    if ds is None:
        return OnaBackend()
    return build_backend(ds.backend, base_url=ds.base_url, token=ds.token, config=ds.config)
