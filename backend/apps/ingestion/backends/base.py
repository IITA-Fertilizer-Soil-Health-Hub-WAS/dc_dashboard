"""Generic data-collection backend interface.

The tool is not ONA-specific: any collection server/tool (ONA, KoboToolbox, ODK
Central, SurveyCTO, a plain REST/CSV endpoint, …) is a `CollectionBackend`. A
backend can:

* **discover** projects (each project == a project here) and their forms,
* **fetch** submissions for a form,
* **sample** a form's field paths (to auto-suggest mappings), and
* **push** an edited submission back to the source (write-back), when supported.

One project is bound to one backend via apps.projects.models.DataSource.
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


@dataclass
class PublishResult:
    """Outcome of pushing an XLSForm to a collection server."""

    ok: bool
    server_form_id: str | None = None
    version: str = ""
    title: str = ""
    url: str = ""
    message: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class ProvisionResult:
    """Outcome of creating/linking a collector account on the source server.

    `remote_id` is the server's own identifier for the account (ODK Central user
    or app-user id, ONA user pk, Kobo username) so a later grant/revoke can act on
    it. `username` is what the collector signs in / is referenced with. `secret`
    is a one-time password or token the server generated, surfaced once so an
    admin can hand it to the collector; it is not stored in cleartext.
    """

    ok: bool
    remote_id: str = ""
    username: str = ""
    secret: str = ""
    url: str = ""
    message: str = ""
    already_existed: bool = False


class CollectionBackend:
    """Abstract backend. Subclasses set `type`/`label` and implement the methods."""

    type: str = ""
    label: str = ""
    supports_discovery: bool = False
    supports_writeback: bool = False
    supports_publish: bool = False
    supports_provisioning: bool = False

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

    def get_form_schema(self, form_id) -> list[dict[str, Any]]:
        """The form's field schema (flat list of {path,label,group,type}) so
        submissions render with human labels. Default: unsupported (empty)."""
        return []

    def list_attachments(self, submission) -> list[dict[str, Any]]:
        """A submission's media descriptors ({name, mimetype, is_image, question, …}).
        Default: read the record's embedded `_attachments` (ONA/Kobo). Servers that
        don't embed them (ODK Central) override to look them up."""
        from apps.ingestion.attachments import parse_attachments

        return parse_attachments(getattr(submission, "raw_payload", None))

    def fetch_attachment(self, attachment: dict[str, Any]) -> tuple[bytes, str]:
        """Fetch one media attachment's bytes + content-type, given a descriptor
        from `list_attachments`, so the app can proxy photos into the review screen
        with the backend's own credentials. Default: unsupported."""
        raise NotImplementedError(f"{self.label or self.type} does not support attachments")

    # --- write-back ---
    def push_edit(self, submission, changes: dict[str, Any]) -> WriteResult:
        """Push reviewer edits to the source record. Default: unsupported."""
        return WriteResult(ok=False, message=f"{self.label or self.type} does not support write-back")

    # --- publish ---
    def publish_form(self, xlsx: bytes, *, form_id: str = "", title: str = "") -> PublishResult:
        """Push an XLSForm to the server so the collection app can download it.

        Default: unsupported. Subclasses for ODK-family servers convert + publish
        the form server-side and return its server form id / version.
        """
        return PublishResult(
            ok=False, message=f"{self.label or self.type} does not support form publishing"
        )

    # --- provisioning ---
    def provision_account(
        self,
        *,
        username: str,
        email: str = "",
        full_name: str = "",
        remote_project_id: str = "",
    ) -> ProvisionResult:
        """Create (or find) an account for a collector on the source server, and
        grant it access to ``remote_project_id`` when given.

        This lets the platform mirror its own accounts onto the collection tool
        so a new user can sign in to collect without a second manual step. The
        default is unsupported; ODK-family backends override it against their
        user / app-user APIs.

        Implementations must be idempotent: if the account already exists, return
        ``ok=True, already_existed=True`` rather than erroring, so re-runs (and the
        grant-time trigger firing after the user-creation trigger) are safe.
        """
        return ProvisionResult(
            ok=False, message=f"{self.label or self.type} does not support account provisioning"
        )
