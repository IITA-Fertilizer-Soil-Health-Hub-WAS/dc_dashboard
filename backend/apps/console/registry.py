"""Registry of models manageable from the in-app console.

Each entry drives a generic CRUD UI (list / create / edit / delete) rendered
inside the app shell, so the management screens feel like one product instead of
bouncing to the separate Django admin. Read-only entries (system-produced data)
get list + detail only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from apps.accounts.models import User
from apps.fieldwork.models import CollectionUnit, Job
from apps.kpi.models import AlertEvent, AlertRule
from apps.rbac.models import UseCaseAccessRequest, UseCaseMembership
from apps.submissions.models import Enumerator, Household, Submission
from apps.usecases.models import (
    Country,
    Crop,
    EventScheduleItem,
    FieldMapping,
    FormDefinition,
    Organization,
    Region,
    Stage,
    Trial,
    UseCase,
)
from apps.validation.models import ValidationFlag, ValidationRule

from .actions import USECASE_ACTIONS, USER_ACTIONS, Action


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
    # ---- Geography: the region → country hierarchy use cases hang off ----
    Managed("regions", Region, "Regions", "Geography",
            list_display=["organization", "code", "name"],
            form_fields=["organization", "code", "name"], search_fields=["code", "name"],
            icon="public", description="Geographic regions a Regional Coordinator oversees."),
    Managed("countries", Country, "Countries", "Geography",
            list_display=["name", "code", "region"],
            form_fields=["region", "code", "name"], search_fields=["code", "name"],
            icon="flag", description="Countries within a region."),
    # ---- Configuration: how a use case is defined & ingested ----
    Managed("use-cases", UseCase, "Use cases", "Configuration",
            list_display=["code", "name", "organization", "country", "is_active",
                          "config_version", "plugin_path"],
            form_fields=["code", "name", "organization", "country", "unit_type", "is_active",
                         "countries", "enid_patterns", "hhid_patterns", "plugin_path",
                         "timezone", "household_label"],
            search_fields=["code", "name"], icon="category", actions=USECASE_ACTIONS,
            description="Projects you monitor — ONA forms, ID patterns, sync."),
    Managed("forms", FormDefinition, "Forms", "Configuration",
            list_display=["use_case", "title", "role", "server_form_id", "publish_status",
                          "version"],
            form_fields=["use_case", "title", "ona_form_id", "server_form_id", "role", "crop",
                         "season", "system_vars_drop"],
            search_fields=["server_form_id", "title"], icon="description",
            description="Forms feeding each use case (onboarded or published)."),
    Managed("field-mappings", FieldMapping, "Field mappings", "Configuration",
            list_display=["form", "target_field", "transform", "required", "order"],
            form_fields=["form", "target_field", "source_paths", "transform",
                         "transform_args", "required", "order"],
            search_fields=["target_field"], icon="swap_horiz",
            description="Map raw ONA fields to canonical fields."),
    Managed("event-schedule", EventScheduleItem, "Event schedule", "Configuration",
            list_display=["use_case", "event_key", "sequence", "anchor", "offset_days"],
            form_fields=["use_case", "event_key", "sequence", "anchor", "offset_days",
                         "crop_overrides", "grace_days"],
            search_fields=["event_key"], icon="event",
            description="Visit timeline & day offsets driving status colours."),
    Managed("crops", Crop, "Crops", "Configuration",
            list_display=["use_case", "name", "aliases"],
            form_fields=["use_case", "name", "aliases"], search_fields=["name"], icon="grass",
            description="Crops and their ONA name aliases."),
    Managed("trials", Trial, "Trials", "Configuration",
            list_display=["use_case", "name", "code"],
            form_fields=["use_case", "name", "code"], search_fields=["name"], icon="science",
            description="Trial / experiment types."),
    Managed("stages", Stage, "Stages", "Configuration",
            list_display=["use_case", "name"],
            form_fields=["use_case", "name"], search_fields=["name"], icon="timeline",
            description="Research / Validation / Piloting."),
    Managed("validation-rules", ValidationRule, "Validation rules", "Configuration",
            list_display=["use_case", "code", "rule_type", "severity", "is_enabled"],
            form_fields=["use_case", "code", "rule_type", "params", "severity",
                         "auto_flag_state", "is_enabled"],
            search_fields=["code"], icon="rule",
            description="Checks that flag submissions for review."),
    # ---- Access: who can see & act ----
    Managed("users", User, "Users", "Accounts & roles",
            list_display=["user_id", "email", "full_name", "organization", "is_active",
                          "is_staff", "is_superuser", "approved_at"],
            form_fields=["email", "full_name", "phone", "organization", "is_active",
                         "email_verified", "is_staff", "is_superuser"],
            search_fields=["user_id", "email", "full_name"], ordering=["email"], icon="person",
            actions=USER_ACTIONS, description="People and account approval status."),
    Managed("memberships", UseCaseMembership, "Memberships", "Accounts & roles",
            list_display=["user", "use_case", "country", "region", "role", "granted_by",
                          "created_at"],
            form_fields=["user", "use_case", "country", "region", "role"],
            search_fields=["user__email", "use_case__code"], icon="group",
            description="Who can access which use case / country / region, and their role."),
    Managed("access-requests", UseCaseAccessRequest, "Access requests", "Accounts & roles",
            list_display=["user", "use_case", "status", "decided_by", "decided_at",
                          "created_at"],
            search_fields=["user__email", "use_case__code"], readonly=True, icon="pending_actions",
            description="Self-service requests to join a project (read-only)."),
    # ---- Field data: the records being monitored ----
    Managed("jobs", Job, "Jobs", "Field data",
            list_display=["use_case", "name", "form", "status", "target_count", "deadline"],
            form_fields=["use_case", "name", "form", "target_count", "start_date", "deadline",
                         "status", "assigned_to"],
            search_fields=["name"], icon="assignment",
            description="Data-collection assignments — form, target, deadline, enumerators."),
    Managed("collection-units", CollectionUnit, "Collection units", "Field data",
            list_display=["use_case", "code", "name", "country", "region", "district"],
            form_fields=["use_case", "code", "name", "lat", "lon", "country", "region",
                         "district", "attributes"],
            search_fields=["code", "name"], icon="place",
            description="Plots / farmers-households planned for collection."),
    Managed("enumerators", Enumerator, "Enumerators", "Field data",
            list_display=["use_case", "enid", "first_name", "surname", "user", "is_test"],
            form_fields=["use_case", "enid", "first_name", "surname", "phone", "user",
                         "is_test"],
            search_fields=["enid", "first_name", "surname"], icon="badge",
            description="Field staff collecting data, linked to platform accounts."),
    Managed("households", Household, "Households", "Field data",
            list_display=["use_case", "hhid", "enumerator", "country", "site_selection_date"],
            form_fields=["use_case", "hhid", "enumerator", "lat", "lon", "country",
                         "site_selection_date"],
            search_fields=["hhid"], icon="home_work",
            description="Households / plots enrolled in trials."),
    Managed("submissions", Submission, "Submissions", "Field data",
            list_display=["use_case", "ona_uuid", "enumerator", "collected_by", "household",
                          "event_key", "event_date", "ingested_at"],
            search_fields=["ona_uuid"], readonly=True, ordering=["-ingested_at"],
            icon="inventory_2", description="Raw submissions ingested from ONA (read-only)."),
    Managed("validation-flags", ValidationFlag, "Validation flags", "Field data",
            list_display=["submission", "rule", "message", "severity", "status"],
            search_fields=["message"], readonly=True, icon="flag",
            description="Open issues raised by validation rules (read-only)."),
    # ---- Monitoring: M&E threshold alerts ----
    Managed("alert-rules", AlertRule, "Alert rules", "Monitoring",
            list_display=["use_case", "name", "metric", "comparator", "threshold",
                          "consecutive_days", "severity", "is_enabled"],
            form_fields=["use_case", "name", "metric", "comparator", "threshold",
                         "consecutive_days", "severity", "notify_emails", "is_enabled"],
            search_fields=["name"], icon="notifications_active",
            description="Threshold rules that raise M&E alerts and email watchers."),
    Managed("alert-events", AlertEvent, "Alert events", "Monitoring",
            list_display=["created_at", "use_case", "rule", "severity", "observed_value"],
            search_fields=["message"], readonly=True, ordering=["-created_at"],
            icon="warning", description="Fired alerts — append-only log (read-only)."),
]

REGISTRY: dict[str, Managed] = {m.key: m for m in _ENTRIES}

# Console sections a coordinator may manage, scoped to their own projects — their
# configuration and field data. Tenancy / Geography / Accounts stay hub-operator
# (staff) only; coordinators handle access through the in-app Team & access screen
# (so access-requests is intentionally NOT a separate console section for them).
COORDINATOR_CONSOLE_KEYS: set[str] = {
    "forms", "field-mappings", "event-schedule", "crops", "trials", "stages",
    "validation-rules", "jobs", "collection-units", "enumerators", "households",
    "submissions", "validation-flags", "alert-rules", "alert-events",
}

# Field-data sections an ordinary member (viewer / enumerator) may VIEW, read-only
# and scoped to projects they belong to. They already see this data via the project
# tabs; this surfaces it in the console rail. Never editable for a plain member.
MEMBER_READ_KEYS: set[str] = {
    "submissions", "validation-flags", "enumerators", "collection-units", "households",
}

# ORM lookup from each coordinator-visible section to its use case id, used to
# scope the list to the coordinator's own projects.
USECASE_FILTER_PATHS: dict[str, str] = {
    "forms": "use_case",
    "field-mappings": "form__use_case",
    "event-schedule": "use_case",
    "crops": "use_case",
    "trials": "use_case",
    "stages": "use_case",
    "validation-rules": "use_case",
    "jobs": "use_case",
    "collection-units": "use_case",
    "enumerators": "use_case",
    "households": "use_case",
    "submissions": "use_case",
    "validation-flags": "submission__use_case",
    "alert-rules": "use_case",
    "alert-events": "use_case",
    "access-requests": "use_case",
}


def _visible_console_keys(user) -> set[str] | None:
    """The console sections a user may OPEN: None means all (staff); otherwise a
    set. Coordinators get their manage subset; ordinary members who belong to at
    least one project get read-only field data; everyone else gets nothing."""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return set()
    if user.is_staff:
        return None  # everything
    from apps.rbac.permissions import can_manage_access, visible_use_cases

    if can_manage_access(user):
        return COORDINATOR_CONSOLE_KEYS
    if visible_use_cases(user).exists():
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
    "use-cases": "organization",
    "forms": "use_case__organization",
    "field-mappings": "form__use_case__organization",
    "event-schedule": "use_case__organization",
    "crops": "use_case__organization",
    "trials": "use_case__organization",
    "stages": "use_case__organization",
    "validation-rules": "use_case__organization",
    "jobs": "use_case__organization",
    "collection-units": "use_case__organization",
    "users": "organization",
    "enumerators": "use_case__organization",
    "households": "use_case__organization",
    "submissions": "use_case__organization",
    "validation-flags": "submission__use_case__organization",
    "access-requests": "use_case__organization",
}

# Group order for sidebar rendering.
GROUPS: list[str] = ["Tenancy", "Geography", "Configuration", "Accounts & roles", "Field data"]


def grouped() -> list[tuple[str, list[Managed]]]:
    """Return [(group, [Managed, ...]), ...] in defined order for the sidebar."""
    return [(g, [m for m in _ENTRIES if m.group == g]) for g in GROUPS]
