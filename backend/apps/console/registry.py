"""Registry of models manageable from the in-app console.

Each entry drives a generic CRUD UI (list / create / edit / delete) rendered
inside the app shell, so the management screens feel like one product instead of
bouncing to the separate Django admin. Read-only entries (system-produced data)
get list + detail only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from apps.accounts.models import User, UserProfile
from apps.fieldwork.models import CollectionUnit, Job
from apps.kpi.models import AlertEvent, AlertRule
from apps.projects.models import (
    Country,
    Crop,
    EventScheduleItem,
    FieldMapping,
    FormDefinition,
    Organization,
    Project,
    Region,
    Trial,
)
from apps.rbac.models import Membership, ProjectAccessRequest
from apps.review.models import RejectionReason
from apps.submissions.models import Enumerator
from apps.validation.models import ValidationRule

from .actions import PROJECT_ACTIONS, USER_ACTIONS, Action


@dataclass(frozen=True)
class Managed:
    key: str
    model: type
    label: str
    group: str
    list_display: list[str]
    form_fields: list[str] | None = None
    search_fields: list[str] = field(default_factory=list)
    ordering: list[str] | None = None
    readonly: bool = False
    icon: str = "table_rows"
    description: str = ""  # shown as a tooltip in the sidebar
    actions: tuple[Action, ...] = ()

    @property
    def singular(self) -> str:
        return str(self.model._meta.verbose_name)


# Order here defines sidebar order within each group.
_ENTRIES: list[Managed] = [
    # ---- Tenancy: the institutions (organizations) that own everything ----
    Managed("organizations", Organization, "Institutions", "Tenancy",
            list_display=["code", "name", "is_active", "database_alias"],
            form_fields=["code", "name", "is_active", "database_alias"],
            search_fields=["code", "name"], icon="domain",
            description="Institutions (tenants) — each owns its own data."),
    # ---- Geography: the region → country hierarchy projects hang off ----
    Managed("regions", Region, "Regions", "Geography",
            list_display=["organization", "code", "name"],
            form_fields=["organization", "code", "name"], search_fields=["code", "name"],
            icon="public", description="Geographic regions a Regional Coordinator oversees."),
    Managed("countries", Country, "Countries", "Geography",
            list_display=["name", "code", "region"],
            form_fields=["region", "code", "name"], search_fields=["code", "name"],
            icon="flag", description="Countries within a region."),
    # ---- Configuration: how a project is defined & ingested ----
    Managed("projects", Project, "Projects", "Configuration",
            list_display=["code", "name", "organization", "country", "is_active",
                          "allow_access_requests", "config_version", "plugin_path"],
            form_fields=["code", "name", "description", "organization", "country", "unit_type",
                         "is_active", "allow_access_requests", "countries", "enid_patterns",
                         "hhid_patterns", "plugin_path", "timezone", "household_label"],
            search_fields=["code", "name"], icon="category", actions=PROJECT_ACTIONS,
            description="Projects you monitor — ONA forms, ID patterns, sync."),
    Managed("forms", FormDefinition, "Forms", "Configuration",
            list_display=["project", "title", "role", "server_form_id", "publish_status",
                          "version"],
            form_fields=["project", "title", "ona_form_id", "server_form_id", "role", "crop",
                         "season", "system_vars_drop"],
            search_fields=["server_form_id", "title"], icon="description",
            description="Forms feeding each project (onboarded or published)."),
    # Field mappings are edited inline per form (Forms → Mappings), so the flat
    # console section is routable but not a separate Configuration nav item.
    Managed("field-mappings", FieldMapping, "Field mappings", "Operations",
            list_display=["form", "target_field", "transform", "required", "order"],
            form_fields=["form", "target_field", "source_paths", "transform",
                         "transform_args", "required", "order"],
            search_fields=["target_field"], icon="swap_horiz",
            description="Map raw ONA fields to canonical fields."),
    Managed("event-schedule", EventScheduleItem, "Event schedule", "Configuration",
            list_display=["project", "event_key", "sequence", "anchor", "offset_days"],
            form_fields=["project", "event_key", "sequence", "anchor", "offset_days",
                         "crop_overrides", "grace_days"],
            search_fields=["event_key"], icon="event",
            description="Visit timeline & day offsets driving status colours."),
    Managed("crops", Crop, "Crops", "Configuration",
            list_display=["project", "name", "aliases"],
            form_fields=["project", "name", "aliases"], search_fields=["name"], icon="grass",
            description="Crops and their ONA name aliases."),
    Managed("trials", Trial, "Trials", "Configuration",
            list_display=["project", "name", "code"],
            form_fields=["project", "name", "code"], search_fields=["name"], icon="science",
            description="Trial / experiment types (linked to submissions at ingest)."),
    Managed("validation-rules", ValidationRule, "Validation rules", "Configuration",
            list_display=["project", "code", "rule_type", "severity", "is_enabled"],
            form_fields=["project", "code", "rule_type", "params", "severity",
                         "auto_flag_state", "is_enabled"],
            search_fields=["code"], icon="rule",
            description="Checks that flag submissions for review."),
    Managed("rejection-reasons", RejectionReason, "Rejection reasons", "Configuration",
            list_display=["project", "code", "label", "order", "is_active"],
            form_fields=["project", "code", "label", "order", "is_active"],
            search_fields=["code", "label"], icon="block",
            description="Categorised reasons a reviewer can decline a submission for."),
    # ---- Access: who can see & act ----
    Managed("users", User, "Users", "Accounts & roles",
            list_display=["user_id", "email", "full_name", "organization", "is_active",
                          "is_staff", "is_superuser", "approved_at"],
            form_fields=["email", "full_name", "phone", "organization", "is_active",
                         "email_verified", "is_staff", "is_superuser"],
            search_fields=["user_id", "email", "full_name"], ordering=["email"], icon="person",
            actions=USER_ACTIONS, description="People and account approval status."),
    Managed("memberships", Membership, "Memberships", "Accounts & roles",
            list_display=["user", "project", "country", "region", "role", "granted_by",
                          "created_at"],
            form_fields=["user", "project", "country", "region", "role"],
            search_fields=["user__email", "project__code"], icon="group",
            description="Who can access which project / country / region, and their role."),
    Managed("access-requests", ProjectAccessRequest, "Access requests", "Accounts & roles",
            list_display=["user", "project", "status", "decided_by", "decided_at",
                          "created_at"],
            search_fields=["user__email", "project__code"], readonly=True, icon="pending_actions",
            description="Self-service requests to join a project (read-only)."),
    Managed("user-profiles", UserProfile, "User profiles", "Accounts & roles",
            list_display=["user", "full_name", "gender", "country", "completed_at"],
            search_fields=["user__email", "user__full_name"], readonly=True,
            icon="badge", description="The register-once identity profiles (read-only)."),
    # Jobs live in the sidebar's Manage section ("Jobs & assignments"), not the
    # config console — so their group is intentionally outside GROUPS (routable +
    # editable, but not repeated in the Field data list). Same pattern as Monitoring.
    Managed("jobs", Job, "Jobs", "Operations",
            list_display=["project", "name", "form", "status", "target_count", "deadline"],
            form_fields=["project", "name", "form", "target_count", "start_date", "deadline",
                         "status", "assigned_to"],
            search_fields=["name"], icon="assignment",
            description="Data-collection assignments — form, target, deadline, enumerators."),
    # Collection units are a top-level project workspace link (same level as
    # Dashboard), so the section is routable but not repeated in a console group.
    Managed("collection-units", CollectionUnit, "Collection units", "Operations",
            list_display=["project", "code", "name", "country", "region", "district"],
            form_fields=["project", "code", "name", "lat", "lon", "country", "region",
                         "district", "attributes"],
            search_fields=["code", "name"], icon="place",
            description="The units data is collected on — farmers / households / plots."),
    # The enumerator roster is edited from the project's Enumerators tab ("Manage
    # roster"), so it's a single sidebar concept — group kept outside GROUPS
    # (routable + editable, not a second "Enumerators" console item).
    Managed("enumerators", Enumerator, "Enumerators", "Operations",
            list_display=["project", "enid", "first_name", "surname", "user", "is_test"],
            form_fields=["project", "enid", "first_name", "surname", "phone", "user",
                         "is_test"],
            search_fields=["enid", "first_name", "surname"], icon="badge",
            description="Field staff collecting data, linked to platform accounts."),
    # Raw submissions and validation flags are viewed richly on the project's Data
    # and Issues tabs — no duplicate console section for them.
    # ---- Monitoring: M&E threshold alerts ----
    Managed("alert-rules", AlertRule, "Alert rules", "Monitoring",
            list_display=["project", "name", "metric", "comparator", "threshold",
                          "consecutive_days", "severity", "is_enabled"],
            form_fields=["project", "name", "metric", "comparator", "threshold",
                         "consecutive_days", "severity", "notify_emails", "is_enabled"],
            search_fields=["name"], icon="notifications_active",
            description="Threshold rules that raise M&E alerts and email watchers."),
    Managed("alert-events", AlertEvent, "Alert events", "Monitoring",
            list_display=["created_at", "project", "rule", "severity", "observed_value"],
            search_fields=["message"], readonly=True, ordering=["-created_at"],
            icon="warning", description="Fired alerts — append-only log (read-only)."),
]

REGISTRY: dict[str, Managed] = {m.key: m for m in _ENTRIES}

# Console sections a coordinator may manage, scoped to their own projects — their
# configuration and field data. Tenancy / Geography / Accounts stay hub-operator
# (staff) only; coordinators handle access through the in-app Team & access screen
# (so access-requests is intentionally NOT a separate console section for them).
COORDINATOR_CONSOLE_KEYS: set[str] = {
    "forms", "field-mappings", "event-schedule", "crops", "trials",
    "validation-rules", "rejection-reasons", "jobs", "collection-units",
    "enumerators",
    "alert-rules", "alert-events",
}

# Field-data sections an ordinary member (viewer / enumerator) may VIEW, read-only
# and scoped to projects they belong to. They already see this data via the project
# tabs; this surfaces it in the console rail. Never editable for a plain member.
MEMBER_READ_KEYS: set[str] = {
    "enumerators", "collection-units",
}

# ORM lookup from each coordinator-visible section to its project id, used to
# scope the list to the coordinator's own projects.
PROJECT_FILTER_PATHS: dict[str, str] = {
    "forms": "project",
    "field-mappings": "form__project",
    "event-schedule": "project",
    "crops": "project",
    "trials": "project",
    "validation-rules": "project",
    "rejection-reasons": "project",
    "jobs": "project",
    "collection-units": "project",
    "enumerators": "project",
    "alert-rules": "project",
    "alert-events": "project",
    "access-requests": "project",
}


def _visible_console_keys(user) -> set[str] | None:
    """The console sections a user may OPEN: None means all (staff); otherwise a
    set. Coordinators get their manage subset; ordinary members who belong to at
    least one project get read-only field data; everyone else gets nothing."""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return set()
    if user.is_staff:
        return None  # everything
    from apps.rbac.permissions import can_manage_access, visible_projects

    if can_manage_access(user):
        return COORDINATOR_CONSOLE_KEYS
    if visible_projects(user).exists():
        return MEMBER_READ_KEYS
    return set()


def console_key_allowed(user, key: str) -> bool:
    """Whether `user` may open (view) this console section."""
    keys = _visible_console_keys(user)
    return keys is None or key in keys


def console_can_edit(user, key: str) -> bool:
    """Whether `user` may mutate this section. Members are always read-only;
    read-only sections are never editable; coordinators only their own scope."""
    if not console_key_allowed(user, key):
        return False
    m = REGISTRY.get(key)
    if m is None or m.readonly:
        return False
    if getattr(user, "is_staff", False):
        return True
    from apps.rbac.permissions import can_manage_access

    return can_manage_access(user) and key in COORDINATOR_CONSOLE_KEYS


def grouped_for(user) -> list[tuple[str, list[Managed]]]:
    """Sidebar groups visible to `user`: everything for staff; the coordinator
    manage subset; or read-only field data for an ordinary project member."""
    keys = _visible_console_keys(user)
    if keys is None:
        return grouped()
    if not keys:
        return []
    out = []
    for group, items in grouped():
        vis = [m for m in items if m.key in keys]
        if vis:
            out.append((group, vis))
    return out

# ORM lookup from each tenant-scoped section to its owning Organization, used by
# the hub operator's per-institution filter on console lists. Sections not listed
# here (e.g. Institutions themselves) are not filtered.
ORG_FILTER_PATHS: dict[str, str] = {
    "regions": "organization",
    "countries": "region__organization",
    "projects": "organization",
    "forms": "project__organization",
    "field-mappings": "form__project__organization",
    "event-schedule": "project__organization",
    "crops": "project__organization",
    "trials": "project__organization",
    "validation-rules": "project__organization",
    "jobs": "project__organization",
    "collection-units": "project__organization",
    "users": "organization",
    "enumerators": "project__organization",
    "access-requests": "project__organization",
}

# Group order for sidebar rendering.
GROUPS: list[str] = ["Tenancy", "Geography", "Configuration", "Accounts & roles"]


def grouped() -> list[tuple[str, list[Managed]]]:
    """Return [(group, [Managed, ...]), ...] in defined order for the sidebar."""
    return [(g, [m for m in _ENTRIES if m.group == g]) for g in GROUPS]
