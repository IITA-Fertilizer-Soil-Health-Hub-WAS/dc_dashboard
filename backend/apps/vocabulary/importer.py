"""Load Terminag CSVs into the DB, and match variable names against them.

The importer is deliberately format-tolerant: Terminag's ``variables_*.csv`` and
``values_*.csv`` tables share a stable first column (``name``) but differ in the
rest, so we read by header and ignore columns we don't model (keeping the extras
on ``VocabularyValue.extra``).
"""
from __future__ import annotations

import csv
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .models import VocabularyValue, VocabularyVariable


class VocabularySyncError(RuntimeError):
    """Cloning or reading the vocabulary repo failed."""

_YES = {"yes", "true", "1", "y"}


def _to_bool(v: str | None) -> bool:
    return (v or "").strip().lower() in _YES


def _to_float(v: str | None):
    v = (v or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _norm(name: str) -> str:
    """Normalise a variable name for matching: lowercase, collapse spaces/dashes
    to underscores, strip units in brackets."""
    n = (name or "").strip().lower()
    n = re.sub(r"\(.*?\)", "", n)          # drop "(cm)" style unit hints
    n = re.sub(r"[\s\-]+", "_", n.strip())
    n = re.sub(r"[^a-z0-9_]", "", n)
    return n.strip("_")


@dataclass
class ImportReport:
    variables: int = 0
    values: int = 0
    tables: list[str] = field(default_factory=list)


def import_from_dir(root: str | Path) -> ImportReport:
    """Import every ``variables/*.csv`` and ``values/*.csv`` under ``root``.
    Idempotent: rows are upserted by their natural key."""
    root = Path(root)
    report = ImportReport()

    for path in sorted((root / "variables").glob("variables_*.csv")):
        category = path.stem.replace("variables_", "")
        for row in _rows(path):
            name = (row.get("name") or "").strip()
            if not name:
                continue
            VocabularyVariable.objects.update_or_create(
                name=name,
                defaults={
                    "category": category,
                    "data_type": (row.get("type") or "").strip(),
                    "unit": (row.get("unit") or "").strip(),
                    "required": _to_bool(row.get("required")),
                    "multiple_allowed": _to_bool(row.get("multiple_allowed")),
                    "value_list": (row.get("vocabulary") or "").strip(),
                    "valid_min": _to_float(row.get("valid_min")),
                    "valid_max": _to_float(row.get("valid_max")),
                    "description": (row.get("description") or "").strip(),
                    "obo": (row.get("obo") or "").strip(),
                },
            )
            report.variables += 1
        report.tables.append(path.name)

    for path in sorted((root / "values").glob("values_*.csv")):
        list_name = path.stem.replace("values_", "")
        for row in _rows(path):
            name = (row.get("name") or "").strip()
            if not name:
                continue
            extra = {k: v for k, v in row.items()
                     if k not in ("name", "is_preferred") and v not in (None, "")}
            VocabularyValue.objects.update_or_create(
                list_name=list_name, name=name,
                defaults={
                    "is_preferred": _to_bool(row.get("is_preferred")) if "is_preferred" in row else True,
                    "extra": extra,
                },
            )
            report.values += 1
        report.tables.append(path.name)

    return report


def sync_from_repo(repo_url: str) -> ImportReport:
    """Shallow-clone ``repo_url`` to a temp dir and import it. Used by the daily
    Celery task and the management command so both share one code path."""
    if not repo_url:
        raise VocabularySyncError("No vocabulary repo URL configured.")
    with tempfile.TemporaryDirectory() as tmp:
        try:
            subprocess.run(["git", "clone", "--depth", "1", repo_url, tmp],
                           check=True, capture_output=True, text=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            raise VocabularySyncError(f"Clone failed: {getattr(exc, 'stderr', exc)}")
        root = Path(tmp)
        if not (root / "variables").is_dir():
            raise VocabularySyncError(f"{repo_url} has no variables/ folder — not a Terminag repo.")
        return import_from_dir(root)


def _rows(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as fh:
        yield from csv.DictReader(fh)


@dataclass
class MatchResult:
    matched: dict  # input name -> VocabularyVariable
    missing: list  # input names with no vocabulary match

    @property
    def coverage(self) -> float:
        total = len(self.matched) + len(self.missing)
        return (len(self.matched) / total) if total else 0.0


def match_terms(names) -> MatchResult:
    """Match input variable names to the vocabulary. Returns the matches and the
    **missing** names (the missing-terms report) so the caller can flag which of a
    protocol/form's variables aren't yet standardised."""
    lookup = {_norm(v.name): v for v in VocabularyVariable.objects.all()}
    matched, missing = {}, []
    for raw in names:
        raw = (raw or "").strip()
        if not raw:
            continue
        hit = lookup.get(_norm(raw))
        if hit is not None:
            matched[raw] = hit
        else:
            missing.append(raw)
    return MatchResult(matched=matched, missing=missing)
