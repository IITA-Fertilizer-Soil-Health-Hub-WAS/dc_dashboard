"""Generic data-collection backend interface.

The tool is not ONA-specific: any collection server/tool (ONA, KoboToolbox, ODK
Central, SurveyCTO, a plain REST/CSV endpoint, …) is a `CollectionBackend`. A
backend can:

* **discover** projects (each project == a use case here) and their forms,
* **fetch** submissions for a form,
* **sample** a form's field paths (to auto-suggest mappings), and
* **push** an edited submission back to the source (write-back), when supported.

One use case is bound to one backend via apps.usecases.models.DataSource.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any


class BackendError(RuntimeError):
    """Raised when a backend cannot talk to its server."""


@dataclass
class RemoteForm:
    id: str
    title: str


@dataclass
class RemoteProject:
    id: str
    name: str
    forms: list[RemoteForm] = field(default_factory=list)


@dataclass
class WriteResult:
    ok: bool
    message: str = ""
    remote_id: str | None = None


class CollectionBackend:
    """Abstract backend. Subclasses set `type`/`label` and implement the methods."""

    type: str = ""
    label: str = ""
    supports_discovery: bool = False
    supports_writeback: bool = False

    def __init__(self, *, base_url: str = "", token: str = "", config: dict | None = None):
        self.base_url = base_url
        self.token = token
        self.config = config or {}

    # --- discovery ---
    def discover_projects(self) -> list[RemoteProject]:
        raise NotImplementedError

    def list_forms(self) -> list[RemoteForm]:
        raise NotImplementedError

    # --- fetch ---
    def iter_submissions(self, form_id) -> Iterator[dict[str, Any]]:
        raise NotImplementedError

    def get_submissions(self, form_id) -> list[dict[str, Any]]:
        return list(self.iter_submissions(form_id))

    def sample_fields(self, form_id) -> list[str]:
        for record in self.iter_submissions(form_id):
            return sorted(record.keys())
        return []

    # --- write-back ---
    def push_edit(self, submission, changes: dict[str, Any]) -> WriteResult:
        """Push reviewer edits to the source record. Default: unsupported."""
        return WriteResult(ok=False, message=f"{self.label or self.type} does not support write-back")
