"""Import GIS-proposed candidate plots (GeoJSON) into Fieldbase.

The upstream site-selection tool exports one FeatureCollection per experiment:
each feature is a candidate plot with POLYGON geometry and properties. Every
feature MUST carry the trial/area key it belongs to (default property `trial_id`)
so candidates group into their trial's set of 3 + backup. Import is idempotent —
re-importing updates in place, keyed on (use_case, trial_key, candidate_ref).
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.common.geo import polygon_centroid
from apps.fieldwork.models import CandidatePlot

# Property names we accept for each field (first match wins) — GIS exports vary.
_TRIAL_KEYS = ("trial_id", "trial_key", "area_id", "trial", "area")
_REF_KEYS = ("candidate_ref", "plot_ref", "ref", "candidate", "plot_id", "id")
_RANK_KEYS = ("rank", "priority", "order")
_ACCESS_KEYS = ("accessibility", "access", "accessibility_class")
_CROP_KEYS = ("cropping_region", "cropping", "crop_region", "agro_zone")
_ROLE_KEYS = ("role", "type", "kind")


@dataclass
class ImportStats:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    trials: int = 0
    errors: list[str] | None = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


def _first(props: dict, keys) -> object:
    for k in keys:
        if k in props and props[k] not in (None, ""):
            return props[k]
    return None


def _role_of(props: dict, ref: str) -> str:
    raw = str(_first(props, _ROLE_KEYS) or "").lower()
    if "backup" in raw or "reserve" in raw or str(ref).lower() in ("backup", "bk"):
        return CandidatePlot.Role.BACKUP
    return CandidatePlot.Role.PRIMARY


def import_candidates(use_case, geojson: dict, *, trial_prop: str | None = None) -> ImportStats:
    """Upsert candidate plots for a use case from a GeoJSON FeatureCollection.

    `trial_prop` overrides which property carries the trial key (else auto-detect
    from `_TRIAL_KEYS`). Features without a trial key, ref, or polygon are skipped
    (recorded in stats.errors), never fatal — one bad feature can't sink the batch.
    """
    stats = ImportStats()
    features = (geojson or {}).get("features") or []
    seen_trials: set[str] = set()
    trial_keys = (trial_prop,) if trial_prop else _TRIAL_KEYS

    for i, feat in enumerate(features):
        if not isinstance(feat, dict):
            stats.skipped += 1
            continue
        props = feat.get("properties") or {}
        geometry = feat.get("geometry") or {}
        trial_key = _first(props, trial_keys)
        ref = _first(props, _REF_KEYS)
        if not trial_key or not ref:
            stats.skipped += 1
            stats.errors.append(f"feature {i}: missing trial key or candidate ref")
            continue
        if geometry.get("type") not in ("Polygon", "MultiPolygon"):
            stats.skipped += 1
            stats.errors.append(f"feature {i} ({trial_key}/{ref}): not a polygon")
            continue

        trial_key, ref = str(trial_key), str(ref)
        rank = _first(props, _RANK_KEYS)
        try:
            rank = int(rank) if rank is not None else 0
        except (TypeError, ValueError):
            rank = 0
        centroid = polygon_centroid(geometry)

        _, created = CandidatePlot.objects.update_or_create(
            use_case=use_case, trial_key=trial_key, candidate_ref=ref,
            defaults={
                "role": _role_of(props, ref),
                "rank": rank,
                "accessibility": str(_first(props, _ACCESS_KEYS) or "")[:32],
                "cropping_region": str(_first(props, _CROP_KEYS) or "")[:128],
                "geometry": geometry,
                "centroid_lat": centroid[0] if centroid else None,
                "centroid_lon": centroid[1] if centroid else None,
                "properties": props,
            },
        )
        stats.created += int(created)
        stats.updated += int(not created)
        seen_trials.add(trial_key)

    stats.trials = len(seen_trials)
    return stats
