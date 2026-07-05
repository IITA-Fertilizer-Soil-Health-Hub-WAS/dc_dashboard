# Validation rules reference

Each rule is a row under **Set up → Validation rules** (per project): a `code`, a
`rule_type`, a `severity` (INFO / WARNING / ERROR), and a `params` JSON object.
An open **ERROR** flag moves the submission to *Flagged* for review; WARNING/INFO
just surface on the **Issues** tab. Re-running is idempotent — a rule that no
longer fires auto-resolves its old flags.

Rules read the **authoritative** (edited) value of each field, so a reviewer's
correction is what gets re-checked.

## Cross-column checks — `CROSS_FIELD`

Combine several columns and test the result. The classic case is *parts that must
add up to a whole*.

```jsonc
// three shares must sum to 100 (±0.5)
{ "fields": ["share_a", "share_b", "share_c"], "compare": "eq",
  "target": 100, "tol": 0.5 }

// four fertiliser splits must sum to the total dose column
{ "fields": ["n1","n2","n3","n4"], "compare": "eq", "rhs_fields": ["dose_total"] }

// a relation between fields: harvested can't exceed planted
{ "fields": ["harvested"], "compare": "lte", "rhs_fields": ["planted"] }

// a combined value must stay in a band
{ "fields": ["len","wid"], "op": "product", "compare": "between",
  "min": 100, "max": 400 }
```

- `op`: `sum` (default) · `mean` · `min` · `max` · `product` · `diff` (first − rest)
- `compare`: `eq` · `neq` · `lte` · `gte` · `lt` · `gt` · `between`
- right-hand side: `target` (constant), or `rhs_fields` (+ optional `rhs_op`), or `min`/`max` for `between`
- `tol`: tolerance for `eq` and the band edges (default 0)
- A **partly-filled** set (some parts entered, some blank/non-numeric) is flagged
  so the arithmetic can't silently pass; an **all-blank** set is skipped.

## Statistical outliers — `NUMERIC_OUTLIER`

Flags values far from the norm even when they're inside the allowed range. The
distribution is learned from the data — no threshold to hand-set.

```jsonc
{ "field": "yield_kg", "method": "zscore", "z": 3.0, "min_n": 20 }   // ~normal fields
{ "field": "yield_kg", "method": "iqr", "k": 1.5 }                   // skewed/heavy-tailed
{ "field": "yield_kg", "group_by": "crop" }                         // per-crop norms
```

- `method`: `zscore` (default; flag `|value − mean| / σ ≥ z`) or `iqr` (flag outside `[Q1 − k·IQR, Q3 + k·IQR]`)
- `group_by`: compare **within** groups (e.g. per crop) so a big crop doesn't make a small crop's values look normal
- `min_n`: minimum values (per group) before the shape is trusted (default 20)

Use `NUMERIC_RANGE` (`{field, min, max}`) when you already know the hard limits.

## Duplicate detection — `UNIQUE_FIELD`

Flags every submission that shares a value in a field meant to be unique — a
duplicate barcode, plot code, or household ID.

```jsonc
{ "field": "barcode", "ignore_blank": true }
```

## Conditionally required — `CONDITIONAL_REQ`

Skip-logic integrity: require fields only when a trigger condition holds (so you
don't over-flag like a plain `REQUIRED_FIELD` would).

```jsonc
{ "when": { "field": "fertiliser_used", "equals": "yes" },
  "require": ["fertiliser_type", "fertiliser_qty"] }

{ "when": { "field": "damage", "not_blank": true }, "require": ["damage_cause"] }
{ "when": { "field": "status", "in": ["sick","dead"] }, "require": ["notes"] }
```

## Other rules (already available)

| Type | What it flags | Key params |
|------|---------------|------------|
| `REQUIRED_FIELD` | Always-required fields left blank | `fields` |
| `NUMERIC_RANGE` | Value outside hard limits / non-numeric | `field`, `min`, `max` |
| `REGEX_ID` | An ID matching none of the allowed patterns | `field`, `patterns` |
| `EVENT_SEQUENCE` | An event submitted while an earlier one is missing | — |
| `DATE_WINDOW` | An expected event whose target date has passed | — |
| `GEO_DISTANCE` | Collected too far from the assigned plot | `max_m` |
| `GEO_CONTAINMENT` | GPS outside the elected plot boundary | — |
| `GEO_DUPLICATE` | Different households sharing one GPS point (curbstoning) | `precision` |
| `SUBMISSION_SPEED` | An enumerator filing an implausible burst | `max`, `window_min` |
| `PHOTO_REUSE` | The same photo reused across households | — |

All rules take an optional `message` to override the default flag text.
