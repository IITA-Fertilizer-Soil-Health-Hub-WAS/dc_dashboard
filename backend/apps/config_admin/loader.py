"""Declarative use-case config <-> database round-trip.

One YAML document fully describes a use case: its meta, crops/trials/stages,
ONA forms + field mappings, event schedule, and validation rules. `import_config`
upserts all of that into the DB (idempotent, transactional, bumps config_version);
`export_config` reproduces the document from the DB. The Admin UI edits the same
rows, so YAML and UI are two front-ends to one source of truth.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from django.db import transaction

from apps.usecases.models import (
    Crop,
    DataSource,
    EventScheduleItem,
    FieldMapping,
    FormDefinition,
    Stage,
    Trial,
    UseCase,
)
from apps.validation.models import ValidationRule


class ConfigError(ValueError):
    """Raised when a config document is structurally invalid."""


def load_yaml(path: str | Path) -> dict[str, Any]:
    with open(path) as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ConfigError(f"Config at {path} must be a mapping")
    return data


def validate_config(data: dict[str, Any]) -> list[str]:
    """Structural pre-flight checks. Returns a list of human-readable problems
    (empty == OK). Cheap to run before import or from the Admin UI 'Validate'
    action. Data-coverage checks against real submissions are added in Phase 4.
    """
    problems: list[str] = []
    meta = data.get("use_case") or {}
    if not meta.get("code"):
        problems.append("use_case.code is required")

    # Forms only need an id here. Roles, field mappings and event modelling vary
    # by project (events can come from a column or from separate forms) and are
    # configured per use case after onboarding — so we don't force them.
    forms = data.get("forms", []) or []
    if not forms:
        problems.append("at least one form is expected")
    for f in forms:
        if not f.get("ona_form_id"):
            problems.append("a form is missing its ona_form_id (form_id)")

    # Event schedule: sequences should be unique and strictly ordered.
    seqs = [ev.get("sequence") for ev in (data.get("event_schedule", []) or [])]
    if len(seqs) != len(set(seqs)):
        problems.append("event_schedule sequences must be unique")

    crop_names = {c["name"] for c in (data.get("crops", []) or [])}
    for ev in data.get("event_schedule", []) or []:
        for crop in (ev.get("crop_overrides") or {}):
            if crop not in crop_names:
                problems.append(
                    f"event {ev.get('event_key')} overrides unknown crop '{crop}'"
                )
    return problems


@transaction.atomic
def import_config(data: dict[str, Any]) -> UseCase:
    """Upsert a use case + all children from a config dict. Idempotent."""
    meta = data.get("use_case") or {}
    code = meta.get("code")
    if not code:
        raise ConfigError("use_case.code is required")

    uc, created = UseCase.objects.get_or_create(code=code, defaults={"name": meta.get("name", code)})
    # Every use case belongs to a tenant: honour an explicit organization code,
    # else fall back to the default org (single-tenant deployments).
    from apps.usecases.tenancy import resolve_organization

    org = resolve_organization(meta.get("organization"))
    if org is not None and uc.organization_id is None:
        uc.organization = org
    uc.name = meta.get("name", uc.name)
    uc.is_active = meta.get("is_active", True)
    uc.countries = meta.get("countries", [])
    uc.enid_patterns = meta.get("enid_patterns", [])
    uc.hhid_patterns = meta.get("hhid_patterns", [])
    uc.plugin_path = meta.get("plugin") or ""
    uc.timezone = meta.get("timezone", "UTC")
    uc.household_label = meta.get("household_label", "Household")
    uc.test_ids = meta.get("test_ids", []) or []
    if not created:
        uc.config_version += 1
    uc.save()

    # Data source (which collection server this use case is pulled from).
    ds = data.get("data_source")
    if ds:
        DataSource.objects.update_or_create(
            use_case=uc,
            defaults={
                "backend": ds.get("backend", "ONA"),
                "base_url": ds.get("base_url", "") or "",
                "token": ds.get("token", "") or "",
                "config": ds.get("config", {}) or {},
            },
        )

    # Replace-all for child collections keeps import deterministic and idempotent.
    uc.crops.all().delete()
    uc.trials.all().delete()
    uc.stages.all().delete()
    uc.schedule.all().delete()
    uc.forms.all().delete()  # cascades to FieldMapping
    uc.rules.all().delete()

    crop_by_name: dict[str, Crop] = {}
    for c in data.get("crops", []) or []:
        crop = Crop.objects.create(
            use_case=uc, name=c["name"], aliases=c.get("aliases", []) or []
        )
        crop_by_name[crop.name] = crop

    for t in data.get("trials", []) or []:
        Trial.objects.create(use_case=uc, name=t["name"], code=t.get("code", ""))

    for s in data.get("stages", []) or []:
        name = s if isinstance(s, str) else s["name"]
        Stage.objects.create(use_case=uc, name=name)

    for ev in data.get("event_schedule", []) or []:
        EventScheduleItem.objects.create(
            use_case=uc,
            event_key=ev["event_key"],
            sequence=ev["sequence"],
            anchor=ev.get("anchor", EventScheduleItem.Anchor.EVENT1),
            offset_days=ev.get("offset_days", 0),
            crop_overrides=ev.get("crop_overrides", {}) or {},
            grace_days=ev.get("grace_days", 0),
        )

    for f in data.get("forms", []) or []:
        crop = crop_by_name.get(f["crop"]) if f.get("crop") else None
        form = FormDefinition.objects.create(
            use_case=uc,
            ona_form_id=f["ona_form_id"],
            role=f["role"],
            crop=crop,
            season=f.get("season", ""),
            system_vars_drop=f.get("system_vars_drop", []) or [],
        )
        for i, m in enumerate(f.get("mappings", []) or []):
            FieldMapping.objects.create(
                form=form,
                target_field=m["target"],
                source_paths=m.get("source", []) or [],
                transform=m.get("transform", FieldMapping.Transform.DIRECT),
                transform_args=m.get("transform_args", {}) or {},
                required=m.get("required", False),
                order=m.get("order", i),
            )

    for r in data.get("validation_rules", []) or []:
        ValidationRule.objects.create(
            use_case=uc,
            code=r["code"],
            rule_type=r["type"],
            params=r.get("params", {}) or {},
            severity=r.get("severity", ValidationRule.Severity.WARNING),
            auto_flag_state=r.get("auto_flag_state", True),
            is_enabled=r.get("is_enabled", True),
        )

    return uc


def export_config(uc: UseCase) -> dict[str, Any]:
    """Reproduce a config dict from the DB (inverse of import_config)."""
    data: dict[str, Any] = {
        "use_case": {
            "code": uc.code,
            "name": uc.name,
            "is_active": uc.is_active,
            "countries": uc.countries,
            "enid_patterns": uc.enid_patterns,
            "hhid_patterns": uc.hhid_patterns,
            "plugin": uc.plugin_path or None,
            "timezone": uc.timezone,
            "household_label": uc.household_label,
            "test_ids": uc.test_ids,
        },
        "crops": [{"name": c.name, "aliases": c.aliases} for c in uc.crops.all()],
        "trials": [{"name": t.name, "code": t.code} for t in uc.trials.all()],
        "stages": [s.name for s in uc.stages.all()],
        **(
            {"data_source": {
                "backend": uc.data_source.backend,
                "base_url": uc.data_source.base_url,
                "config": uc.data_source.config,
            }}
            if hasattr(uc, "data_source") else {}
        ),
        "event_schedule": [
            {
                "event_key": ev.event_key,
                "sequence": ev.sequence,
                "anchor": ev.anchor,
                "offset_days": ev.offset_days,
                "crop_overrides": ev.crop_overrides,
                "grace_days": ev.grace_days,
            }
            for ev in uc.schedule.all()
        ],
        "forms": [
            {
                "ona_form_id": f.ona_form_id,
                "role": f.role,
                "crop": f.crop.name if f.crop else None,
                "season": f.season,
                "system_vars_drop": f.system_vars_drop,
                "mappings": [
                    {
                        "target": m.target_field,
                        "source": m.source_paths,
                        "transform": m.transform,
                        "transform_args": m.transform_args,
                        "required": m.required,
                        "order": m.order,
                    }
                    for m in f.mappings.all()
                ],
            }
            for f in uc.forms.all()
        ],
        "validation_rules": [
            {
                "code": r.code,
                "type": r.rule_type,
                "params": r.params,
                "severity": r.severity,
                "auto_flag_state": r.auto_flag_state,
                "is_enabled": r.is_enabled,
            }
            for r in uc.rules.all()
        ],
    }
    return data


def dump_yaml(uc: UseCase) -> str:
    return yaml.safe_dump(export_config(uc), sort_keys=False, allow_unicode=True)
