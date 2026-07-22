"""Reference datasets: import an external table (sampling frame, lab results,
lookup) into a project and reconcile it against field submissions.

This is the "reference dataset" ODK Central / ONA has no notion of — the thing
that lets the platform validate sample IDs, detect planned-but-unsubmitted
samples, and cross-check field values against laboratory results.
"""
from __future__ import annotations

import csv
import io


def norm(value) -> str:
    return str(value).strip() if value is not None else ""


def import_reference_csv(project, *, code, name, kind, key_field, text) -> "ReferenceDataset":
    """Parse a CSV and (re)load it as a project's reference dataset, keyed by
    `key_field`. Replaces any existing rows for the same code (idempotent)."""
    from apps.projects.models import ReferenceDataset, ReferenceRow

    reader = csv.DictReader(io.StringIO(text))
    columns = [c for c in (reader.fieldnames or []) if c]
    if not columns:
        raise ValueError("The file has no header row / columns.")
    if key_field not in columns:
        raise ValueError(
            f"Key column “{key_field}” is not in the file. Columns: {', '.join(columns)}"
        )
    ds, _ = ReferenceDataset.objects.update_or_create(
        project=project, code=code,
        defaults={"name": name, "kind": kind, "key_field": key_field, "columns": columns},
    )
    ds.rows.all().delete()
    seen, rows = set(), []
    for r in reader:
        key = norm(r.get(key_field))
        if not key or key in seen:
            continue  # skip blanks and in-file duplicates (kept unique per dataset)
        seen.add(key)
        rows.append(ReferenceRow(dataset=ds, key=key,
                                 data={c: (r.get(c) or "") for c in columns}))
    ReferenceRow.objects.bulk_create(rows, batch_size=1000)
    ds.row_count = len(rows)
    ds.save(update_fields=["row_count"])
    return ds


def submitted_values(project, field_key) -> set:
    """Distinct, normalized values of a field across a project's submissions
    (authoritative SubmissionValue, falling back to the raw payload)."""
    from apps.submissions.models import Submission, SubmissionValue

    vals: set = set()
    for v in SubmissionValue.objects.filter(
        submission__project=project, field_key=field_key
    ).values_list("current_value", flat=True):
        n = norm(v)
        if n:
            vals.add(n)
    for raw in Submission.objects.filter(project=project).values_list("raw_payload", flat=True):
        if raw:
            n = norm(raw.get(field_key))
            if n:
                vals.add(n)
    return vals


def reconcile(dataset, field_key) -> dict:
    """Compare a dataset's keys against the values submitted for `field_key`:
    matched, missing (planned but never submitted), and unknown (submitted but
    not in the reference)."""
    frame = set(dataset.rows.values_list("key", flat=True))
    submitted = submitted_values(dataset.project, field_key)
    matched = frame & submitted
    missing = frame - submitted
    unknown = submitted - frame
    return {
        "frame": len(frame), "submitted": len(submitted), "matched": len(matched),
        "missing_n": len(missing), "missing": sorted(missing)[:500],
        "unknown_n": len(unknown), "unknown": sorted(unknown)[:500],
        "coverage_pct": round(100 * len(matched) / len(frame), 1) if frame else 0,
    }
