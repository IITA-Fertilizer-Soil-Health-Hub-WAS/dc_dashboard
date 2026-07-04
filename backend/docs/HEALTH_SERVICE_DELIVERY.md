# Health service delivery (OpenSRP-style) — build plan

This is a **program**, not a single feature — a community-health information
system (CHIS) is weeks of work. But Fieldbase already has most of the primitives,
so we build a care-management *layer* on top rather than starting over.

## What we already have (reuse, don't rebuild)

| CHIS concept | Existing Fieldbase primitive |
|---|---|
| Client / beneficiary register | `fieldwork.CollectionUnit` (farmer/household/plot → client) |
| Encounter / visit | `submissions.Submission` (`collection_unit`, `event_key`, `event_date`) |
| Care plan / visit protocol | `projects.EventScheduleItem` (offsets from an anchor date) |
| Overdue / on-time status | the DATE_WINDOW validation engine (green/amber/red) |
| Health-worker tasks | `fieldwork.Job` + `UnitAssignment` |
| Roles / who-can-see | the RBAC hierarchy + multi-tenancy |
| Forms (registration, visit) | the form builder + ODK publish |

So the new work is: a **client-centric view** of that data, plus care-specific
concepts (programmes, enrollment, tasks, indicators) that don't exist yet.

## Phases — all delivered

**Phase 1 — Client register + longitudinal record  ✅**
- `CareProgram` marks a project as a health-service programme (client label).
- Clients list (collection units, visit count, last visit) + a per-client
  **timeline** of encounters.

**Phase 2 — Care plans + coverage  ✅**
- Per-client **visit plan** (done / due / overdue / upcoming) from
  `EventScheduleItem`, reusing the shared event-status engine; programme
  **coverage** view + defaulters.

**Phase 3 — Worker caseload + tasks + referrals  ✅**
- `CareAssignment` (client → worker); reassignment = referral with history.
- **My caseload** worklist (overdue first); coordinators assign/refer from the
  register.

**Phase 4 — Report + indicators  ✅**
- Per-worker breakdown on the coverage page; programme-status **CSV export**;
  care metrics (coverage, defaulters, enrolled) in the self-serve dashboard
  builder.

**Phase 5 — Offline caseload  ✅**
- A worker downloads their caseload (clients + open visits) as CSV to reference
  in the field. Collection itself stays ODK Collect (offline), by design.

## Non-goals (explicitly out of scope for now)
- Clinical decision support / drug dosing.
- EMR-grade audit certification (HIPAA/GDPR clinical compliance) — needs legal.
- Being a full OpenSRP replacement on day one; this is an in-mission CHIS layer.

## Decision checkpoints for the product owner
1. Is the client the individual, or the household? (CollectionUnit can be either.)
2. Which programmes first (e.g. nutrition follow-up, soil-health extension visits)?
3. Do we need referrals in Phase 3, or is a single-worker caseload enough at first?
