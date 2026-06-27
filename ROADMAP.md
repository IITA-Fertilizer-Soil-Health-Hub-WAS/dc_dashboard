# Roadmap — Field data collection & M&E

This platform is a **server-agnostic field data-collection and M&E tool**: it
publishes forms to a collection server, lets coordinators plan and assign field
work, monitors submissions in real time, runs a two-gate review, and reports
M&E KPIs. It orchestrates a collection backend (ONA today; ODK Central later) —
it does **not** reimplement one.

Reference vision: *IITA Data Collection Platform* (DRMU, May 2022). We deliver
its **capabilities** (form lifecycle, roles, real-time monitoring, KPI
dashboard) on our own stack rather than its literal ODK-Central-on-Azure
deployment, because **server-agnostic** is a hard requirement.

## The flow

1. **Platform Admin publishes a form** (uploads an XLSForm → the project's
   backend) and, on success, grants the right coordinators access.
2. **Project** = a trial / survey / data-collection initiative.
3. **Coordinators create jobs** — sets of collection units (plots *or*
   farmers/households) to collect on — and assign the **Enumerator** role.
4. **Enumerators collect in the field, offline**, in ODK Collect / Enketo.
5. **Trial Coordinator (in-country)** monitors in real time → edits data that
   doesn't match reality, or rejects big issues (**Gate 1**).
6. **Regional Coordinator** does **Gate 2** validation → approve = final data;
   else send back to the trial coordinator + enumerator to fix.
7. The platform **auto-flags** quality issues so coordinators do less by hand.
8. **Everything is tracked with M&E KPIs.**

## Offline collection — delegated, never duplicated

Offline-first capture (local form/response storage, GPS/media without signal,
sync on reconnect) is handled by **ODK Collect** (Android) and **Enketo** (web)
— the proven ODK ecosystem. The platform never stores in-progress offline data;
it publishes forms to the server and ingests submissions from it. The
"IITA Data Collect" app is **white-labelled ODK Collect** with the server URL
and Entra ID login pre-configured. A fully in-house PWA, if ever wanted, embeds
**Enketo** for offline rendering/storage. Enumerator identity bridges to the
platform **UserID** at ingest (`collected_by`), so offline records still trace
to a person.

## Already built

Server-agnostic backends (ONA/Kobo/ODK Central) · projects · roles + multi-tenant
isolation · two-gate review (edit/reject → validate → final, or send back) ·
auto-flag via validation rules · pull + write-back · scoped coordinator console ·
access requests · audit trail.

## Gaps to build

### A — Form publishing (XLSForm → server)
A Platform Admin uploads an XLSForm; the platform pushes it to the project's
backend, confirms, auto-maps fields, then access is granted.

- Backend: `CollectionBackend.publish_form(xlsx, project_ref) -> PublishResult`
  (ODK Central `POST /v1/projects/{id}/forms?publish=true`; ONA `POST
  /api/v1/forms`; Kobo import+deploy).
- `FormDefinition`: add `title`, `xlsform`, `server_form_id` (generalises
  `ona_form_id`), `version`, `publish_status`, `published_at`.
- UI: "Publish form" screen → pick project, upload `.xlsx`, push, surface
  conversion warnings, auto-create + auto-map the form.
- Stages (all shipped ✓): A1 backend impls · A2 model + migration · A3 upload UI
  + auto-map · A4 tests.

### B — Jobs / collection units
Coordinators define what to collect on, assign enumerators, set targets +
deadlines; the platform tracks expected vs actual per unit.

- New app `apps/fieldwork`:
  - `UseCase.unit_type` — `PLOT` or `FARMER_HOUSEHOLD`, fixed per project.
  - `CollectionUnit` — project, `code`, `name`, optional `lat/lon`, admin area,
    `attributes` JSON. (Generalises `Household`; folded in later.)
  - `Job` — project, `form`, `target_count`, `start_date`, `deadline`, `status`;
    assigned enumerators; its collection units.
  - `UnitAssignment` — which enumerator collects which unit in a job.
  - `Submission.collection_unit` FK — matched at ingest by an ID field.
- UI: job CRUD (coordinator-scoped) + CSV unit import + enumerator assignment +
  "My assignments" + expected-vs-actual completion.
- Stages (all shipped ✓): B1 models + migration + ingest link · B2 job CRUD +
  CSV import · B3 assignment + "My assignments" · B4 completion tracking · B5
  tests.

### C — M&E KPI dashboard
The doc's Phase 5, in-app. We already ingest into Postgres, so **no separate ETL
service** — a Celery Beat task materialises KPI snapshots (~15-min incremental +
nightly full), and **webhooks** from the server trigger instant ingest for
real-time cards.

- `apps/kpi`: `ProjectKpiDaily`, `EnumeratorKpiDaily`, `FormKpiDaily`,
  `AlertRule`, `AlertEvent` (indexed on date/project/form/enumerator).
- KPI dimensions:
  - **Productivity** — submissions per project/form/enumerator over time; active
    vs dormant forms; enumerator rate; peak hours.
  - **Quality** — constraint-violation & required-missing rates (from validation
    flags); media completeness; duplicate rate; 0–100 quality score.
  - **Coverage** — geopoint completeness; distinct admin units; coverage-gap
    (planned units vs collected); GPS-accuracy distribution.
  - **Timeliness** — sync lag; 7/30-day trend; pace vs target; overdue.
- UI (role-scoped): Overview · Project · Data Quality (heatmap + drilldown) ·
  Enumerator leaderboard + map · Coverage map + gap · Alerts (in-app + email).
- Exports: CSV + GeoJSON shipped (KPI summary, enumerators, units FeatureCollection,
  approved dataset); XLSX + SPSS/STATA (`openpyxl` / `pyreadstat`) optional follow-up.
- Stages (all shipped ✓): C1 models + Beat aggregation · C2 Overview + Project ·
  C3 Quality + Enumerator + Coverage · C4 Alerts (in-app + email, hourly Beat) ·
  C5 exports (CSV + GeoJSON) · C6 tests (written per-stage).

## Sequencing

**A → B → C** (jobs need forms; coverage/pace KPIs need jobs). Productivity &
Quality KPIs can start during C1. Each feature ships in stages with tests and
live verification, committed to `fork/redesign/python`.

## Cross-cutting

- **Real-time:** add submission **webhooks** (ODK Central / ONA) → instant
  ingest, alongside the periodic sync.
- **Auth (Entra ID):** the doc wants Microsoft Entra ID; we use Auth0. Both are
  OIDC — an allauth provider swap (config-level), done at IITA cutover.
- **Server-agnostic** preserved throughout: all server-specific logic stays
  behind `CollectionBackend`.
