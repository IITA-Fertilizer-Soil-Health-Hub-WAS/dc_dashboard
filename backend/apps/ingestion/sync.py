"""Ingestion orchestrator — the generic engine that replaces dataprocessing.R.

For a use case it: pulls each ONA form, normalizes records via config-driven
FieldMappings, upserts Enumerators/Households from the registration forms, and
upserts immutable Submissions + their authoritative SubmissionValues from the
validation forms. Idempotent: keyed on (use_case, ona_uuid) with a content hash
so unchanged records are skipped and reviewer edits are never clobbered.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.submissions.models import Enumerator, Household, Submission, SubmissionValue
from apps.usecases.models import FormDefinition, UseCase

from .backends.registry import get_backend_for
from .normalizer import build_crop_alias_map, normalize_record
from .registry import get_plugin

REGISTRATION_ROLES = {FormDefinition.Role.ENUM_REG, FormDefinition.Role.HH_REG}
VALIDATION_ROLES = {
    FormDefinition.Role.VALIDATION,
    FormDefinition.Role.NOT,
    FormDefinition.Role.INTERCROP,
    FormDefinition.Role.EXTRA,
}


@dataclass
class SyncStats:
    use_case: str
    enumerators: int = 0
    households: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped_test: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "use_case": self.use_case,
            "enumerators": self.enumerators,
            "households": self.households,
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "skipped_test": self.skipped_test,
            "errors": self.errors,
        }


def _hash(record: dict) -> str:
    return hashlib.sha256(
        json.dumps(record, sort_keys=True, default=str).encode()
    ).hexdigest()


def _to_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _fetch(source, form_id):
    """Fetch submissions from a backend (get_submissions) or a legacy client
    (get_data) — keeps test doubles that expose get_data working."""
    fetch = getattr(source, "get_submissions", None) or source.get_data
    return fetch(form_id)


def auto_map_form(form, sample_record: dict) -> int:
    """If a form has no field mappings yet, derive them from a sample submission
    using the onboarding heuristic, and persist them. Returns the count created.
    This makes "onboard -> sync" populate data without manual per-form mapping;
    the mappings can then be refined under Manage -> Forms -> Mappings."""
    from apps.console.onboarding import CANONICAL_TARGETS, suggest_mappings
    from apps.usecases.models import FieldMapping

    by_key = {t["key"]: t for t in CANONICAL_TARGETS}
    chosen = suggest_mappings(sorted(sample_record.keys()))
    created = 0
    for order, (key, path) in enumerate(chosen.items()):
        target = by_key[key]
        args = {"into": ["LAT", "LON", "ALT", "ERR"]} if key == "GEO" else {}
        FieldMapping.objects.create(
            form=form, target_field=key, source_paths=[path],
            transform=target["transform"], transform_args=args, order=order,
        )
        created += 1
    return created


def sync_use_case(use_case: UseCase, backend=None, client=None) -> SyncStats:
    """Sync all of a use case's forms via its data-collection backend.

    `backend` (or legacy `client`) may be injected for testing; otherwise the
    backend bound to the use case's DataSource is used.
    """
    source = backend or client or get_backend_for(use_case)
    stats = SyncStats(use_case=use_case.code)
    plugin = get_plugin(use_case)
    alias_map = build_crop_alias_map(use_case)
    crop_by_name = {c.name: c for c in use_case.crops.all()}
    test_ids = set(use_case.test_ids or [])

    # Not prefetching mappings: auto_map_form may create them mid-loop, and a
    # prefetch cache would hide the new rows.
    forms = list(use_case.forms.all())

    # 1) Registration forms first (enumerators + households are FKs for submissions).
    for form in [f for f in forms if f.role in REGISTRATION_ROLES]:
        records = plugin.pre_ingest(form, _fetch(source, form.server_ref))
        if not form.mappings.exists() and records:
            auto_map_form(form, records[0])
        mappings = list(form.mappings.order_by("order", "target_field"))
        for rec in records:
            mapped = normalize_record(mappings, rec, alias_map)
            if form.role == FormDefinition.Role.ENUM_REG:
                _upsert_enumerator(use_case, mapped, test_ids, stats)
            else:
                _upsert_household(use_case, mapped, stats)

    # 2) Validation forms -> immutable Submissions + authoritative values.
    for form in [f for f in forms if f.role in VALIDATION_ROLES]:
        records = plugin.pre_ingest(form, _fetch(source, form.server_ref))
        if not form.mappings.exists() and records:
            auto_map_form(form, records[0])
        mappings = list(form.mappings.order_by("order", "target_field"))
        for rec in records:
            mapped = normalize_record(mappings, rec, alias_map)
            # Plugins may explode one nested record into multiple normalized rows.
            for row in plugin.normalize(form, rec, mapped):
                _upsert_submission(use_case, form, rec, row, crop_by_name, test_ids, stats)

    return stats


def _upsert_enumerator(use_case, mapped, test_ids, stats) -> None:
    enid = mapped.get("ENID")
    if not enid:
        return
    Enumerator.objects.update_or_create(
        use_case=use_case,
        enid=enid,
        defaults={
            "first_name": mapped.get("ENfirstName") or "",
            "surname": mapped.get("ENSurname") or "",
            "phone": mapped.get("ENphoneNo") or "",
            "is_test": enid in test_ids,
        },
    )
    stats.enumerators += 1


def _upsert_household(use_case, mapped, stats) -> None:
    hhid = mapped.get("HHID")
    if not hhid:
        return
    enumerator = None
    enid = mapped.get("ENID")
    if enid:
        enumerator = Enumerator.objects.filter(use_case=use_case, enid=enid).first()
    Household.objects.update_or_create(
        use_case=use_case,
        hhid=hhid,
        defaults={
            "enumerator": enumerator,
            "lat": _num(mapped.get("LAT")),
            "lon": _num(mapped.get("LON")),
            "alt": _num(mapped.get("ALT")),
            "country": mapped.get("Country") or "",
            "site_selection_date": _to_date(mapped.get("today")),
        },
    )
    stats.households += 1


@transaction.atomic
def _upsert_submission(use_case, form, raw_rec, mapped, crop_by_name, test_ids, stats) -> None:
    enid = mapped.get("ENID")
    if enid and enid in test_ids:
        stats.skipped_test += 1
        return

    # A plugin that explodes one record into several rows supplies a distinct
    # per-row "_uuid" so the exploded submissions don't collide.
    ona_uuid = (
        mapped.get("_uuid")
        or raw_rec.get("_uuid")
        or raw_rec.get("meta/instanceID")
        or _hash(raw_rec)
    )
    content_hash = _hash({**raw_rec, "_row_uuid": ona_uuid})

    # Identities are derived from the data itself, so a project does not need a
    # dedicated registration form. A registration form (if present) is processed
    # first and enriches these with names/contact/geo; here we just ensure they
    # exist so rankings and the household list populate for any project shape.
    enumerator = None
    if enid:
        enumerator, _ = Enumerator.objects.get_or_create(
            use_case=use_case, enid=enid, defaults={"is_test": enid in test_ids}
        )
    hhid = mapped.get("HHID")
    household = None
    if hhid:
        household, _ = Household.objects.get_or_create(
            use_case=use_case, hhid=hhid, defaults={"enumerator": enumerator}
        )
    crop = crop_by_name.get(mapped.get("Crop")) if mapped.get("Crop") else None
    collected_by = _resolve_collector(mapped, enumerator)
    collection_unit = _resolve_collection_unit(use_case, hhid)
    lat, lon = _resolve_location(raw_rec, mapped, household)

    existing = Submission.objects.filter(use_case=use_case, ona_uuid=ona_uuid).first()
    if existing and existing.content_hash == content_hash:
        stats.unchanged += 1
        return

    defaults = {
        "form": form,
        "ona_submission_id": raw_rec.get("_id"),
        "ona_submission_time": _to_datetime(raw_rec.get("_submission_time")),
        "ona_edited": bool(raw_rec.get("_edited")),
        "raw_payload": raw_rec,
        "content_hash": content_hash,
        "enumerator": enumerator,
        "household": household,
        "crop": crop,
        "collected_by": collected_by,
        "collection_unit": collection_unit,
        "event_key": mapped.get("event_key") or "",
        "event_date": _to_date(mapped.get("today")),
        "lat": lat,
        "lon": lon,
    }
    submission, created = Submission.objects.update_or_create(
        use_case=use_case, ona_uuid=ona_uuid, defaults=defaults
    )
    _sync_values(submission, mapped, is_new=created)
    if created:
        stats.created += 1
    else:
        stats.updated += 1


def _resolve_collection_unit(use_case, hhid):
    """Match a submission to its planned collection unit by id (HHID / plot id).
    Only matches existing units — jobs/units are planned ahead of collection."""
    if not hhid:
        return None
    from apps.fieldwork.models import CollectionUnit

    return CollectionUnit.objects.filter(use_case=use_case, code=hhid).first()


def submission_location(raw_rec: dict, mapped: dict):
    """The submission's collected (lat, lon), or (None, None).

    Priority: ONA's config-free ``_geolocation`` ([lat, lon] on every geo
    submission), then a mapped geopoint split into LAT/LON. Re-used by the
    backfill migration, hence module-level."""
    geo = raw_rec.get("_geolocation")
    if isinstance(geo, (list, tuple)) and len(geo) >= 2:
        lat, lon = _num(geo[0]), _num(geo[1])
        if lat is not None and lon is not None:
            return lat, lon
    return _num(mapped.get("LAT")), _num(mapped.get("LON"))


def _resolve_location(raw_rec, mapped, household):
    """The submission's own location, falling back to its household's so older
    household-anchored forms still map."""
    lat, lon = submission_location(raw_rec, mapped)
    if lat is None and household is not None and household.lat is not None:
        return household.lat, household.lon
    return lat, lon


def _resolve_collector(mapped, enumerator):
    """Resolve the platform User who collected a submission.

    Two paths, in priority order:
      1. The mobile app stamps the collector's platform UserID on the record
         (canonical ``USERID``) — resolve it directly. This is the end state.
      2. ONA-era bridge: the submission's enumerator is linked to a User account
         (``Enumerator.user``), so attribute the submission to that account.
    """
    from apps.accounts.models import User

    uid = mapped.get("USERID")
    if uid:
        user = User.objects.filter(user_id=uid).first()
        if user:
            return user
    if enumerator and enumerator.user_id:  # FK id — enumerator linked to an account
        return enumerator.user
    return None


def _sync_values(submission, mapped, *, is_new: bool) -> None:
    """Write field-level values. raw_value is always refreshed from ONA; an
    already-edited current_value is preserved (re-ingest never clobbers edits)."""
    for field_key, value in mapped.items():
        existing = None if is_new else SubmissionValue.objects.filter(
            submission=submission, field_key=field_key
        ).first()
        if existing is None:
            SubmissionValue.objects.update_or_create(
                submission=submission,
                field_key=field_key,
                defaults={
                    "raw_value": value,
                    "current_value": value,
                    "source": SubmissionValue.Source.INGEST,
                },
            )
        else:
            existing.raw_value = value
            if not existing.is_edited:
                existing.current_value = value
            existing.save(update_fields=["raw_value", "current_value", "updated_at"])


def _num(value: Any):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _to_datetime(value: Any):
    if not value:
        return None
    text = str(value)
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text[: len(fmt) + 4], fmt)
            return timezone.make_aware(dt) if timezone.is_naive(dt) else dt
        except ValueError:
            continue
    return None
