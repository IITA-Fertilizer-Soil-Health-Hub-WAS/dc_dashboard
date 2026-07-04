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

## Phases

**Phase 1 — Client register + longitudinal record  *(this commit)***
- `CareProgram` marks a project as a health-service programme (client label,
  active).
- Clients list (the programme's collection units, with last visit + status) and a
  per-client **timeline** of encounters against the visit schedule.

**Phase 2 — Enrollment + care plans**
- Enroll a client into a programme with a start/anchor date; generate the visit
  schedule (from `EventScheduleItem`) as concrete due dates; show
  due / overdue / done per visit.

**Phase 3 — Tasks + worker workflow**
- Per-worker task list (reuse `Job`/`UnitAssignment`): "visit these clients this
  week", complete a task by submitting the visit form; referrals between workers.

**Phase 4 — Indicators + reporting**
- Care indicators (coverage, defaulters, visit adherence) as dashboard widgets
  (reuse the self-serve dashboard builder) + programme-level reports.

**Phase 5 — Offline + scale**
- Field collection stays ODK Collect (offline) as today; add client-list sync so
  a worker can pull their caseload. Longitudinal continuity across visits.

## Non-goals (explicitly out of scope for now)
- Clinical decision support / drug dosing.
- EMR-grade audit certification (HIPAA/GDPR clinical compliance) — needs legal.
- Being a full OpenSRP replacement on day one; this is an in-mission CHIS layer.

## Decision checkpoints for the product owner
1. Is the client the individual, or the household? (CollectionUnit can be either.)
2. Which programmes first (e.g. nutrition follow-up, soil-health extension visits)?
3. Do we need referrals in Phase 3, or is a single-worker caseload enough at first?
