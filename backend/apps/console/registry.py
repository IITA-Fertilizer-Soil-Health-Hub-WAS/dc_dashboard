"""Registry of models manageable from the in-app console.

Each entry drives a generic CRUD UI (list / create / edit / delete) rendered
inside the app shell, so the management screens feel like one product instead of
bouncing to the separate Django admin. Read-only entries (system-produced data)
get list + detail only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from apps.accounts.models import User
from apps.rbac.models import UseCaseMembership
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
    def verbose_plural(self) -> str:
        return self.label

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
            form_fields=["code", "name", "organization", "country", "is_active", "countries",
                         "enid_patterns", "hhid_patterns", "plugin_path", "timezone",
                         "household_label"],
            search_fields=["code", "name"], icon="category", actions=USECASE_ACTIONS,
            description="Projects you monitor — ONA forms, ID patterns, sync."),
    Managed("forms", FormDefinition, "Forms", "Configuration",
            list_display=["use_case", "role", "ona_form_id", "crop", "season"],
            form_fields=["use_case", "ona_form_id", "role", "crop", "season", "system_vars_drop"],
            search_fields=["ona_form_id"], icon="description",
            description="ONA form IDs feeding each use case."),
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
    Managed("users", User, "Users", "Access",
            list_display=["user_id", "email", "full_name", "organization", "is_active",
                          "is_staff", "is_superuser", "approved_at"],
            form_fields=["email", "full_name", "phone", "organization", "is_active",
                         "email_verified", "is_staff", "is_superuser"],
            search_fields=["user_id", "email", "full_name"], ordering=["email"], icon="person",
            actions=USER_ACTIONS, description="People and account approval status."),
    Managed("memberships", UseCaseMembership, "Memberships", "Access",
            list_display=["user", "use_case", "country", "region", "role", "granted_by",
                          "created_at"],
            form_fields=["user", "use_case", "country", "region", "role"],
            search_fields=["user__email", "use_case__code"], icon="group",
            description="Who can access which use case / country / region, and their role."),
    # ---- Field data: the records being monitored ----
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
]

REGISTRY: dict[str, Managed] = {m.key: m for m in _ENTRIES}

# Group order for sidebar rendering.
GROUPS: list[str] = ["Tenancy", "Geography", "Configuration", "Access", "Field data"]


def grouped() -> list[tuple[str, list[Managed]]]:
    """Return [(group, [Managed, ...]), ...] in defined order for the sidebar."""
    return [(g, [m for m in _ENTRIES if m.group == g]) for g in GROUPS]
