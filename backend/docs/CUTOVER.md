# Migration & Cutover Runbook (R Shiny → Django)

This is the operational sequence to move from the legacy R Shiny dashboard to the
Django platform. The code is built and tested; the steps below require production
credentials (ONA token, Auth0 tenant, DB host) and a window to parallel-run.

## 0. Prerequisites
- Postgres + Redis provisioned; `DATABASE_URL`, `CELERY_BROKER_URL` set.
- ONA API token in `ONA_TOKEN` (was `TOKEN1`/`ONA_TOKEN` in the R `.Renviron`).
- Auth0 application configured as a regular OIDC web app; set `AUTH0_DOMAIN`,
  `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET` (enables the OIDC bridge automatically).

## 1. Stand up the app
```bash
python manage.py migrate
python manage.py createsuperuser           # first Platform Admin
python manage.py load_usecase --all        # import config/usecases/*.yaml
```

## 2. Port remaining use cases (config-only)
`config/usecases/sns-rwanda.yaml` is the worked example. For each remaining active
use case (KALRO, Solidaridad-Soy-Advisory, Mercy-Corps-SPROUT, GH-CerLeg-Esoko,
DEMO, BioSSA), author one YAML file:
- Form IDs come from `okapi.R` (the `ona_data_get(form_id=…)` calls).
- Field mappings come from the use case's `rename()/coalesce()/separate()` block in
  `dataprocessing.R` → `FieldMapping` rows (transform DIRECT/COALESCE/SPLIT_GEOPOINT/…).
- Event offsets come from `support_fun.R` `dynamic_colorcodeS` → `event_schedule`.
- ID regexes come from `app.R` `usecase_files` (`patternissues`/`patternissuesE`).
- **BioSSA** sets `plugin: plugins.biossa:BioSSAPlugin` for its nested multi-crop
  repeats (see `plugins/biossa.py`); the rest stays declarative.

Validate before loading:
```bash
python manage.py load_usecase config/usecases/<uc>.yaml --check
python manage.py load_usecase config/usecases/<uc>.yaml
```

## 3. Backfill data & validate
```bash
python manage.py sync_usecase --all     # ONA pull → submissions → validation flags
```
Schedule the daily sync via Celery Beat (`daily-ona-sync`, already configured) —
this replaces the R `0 0 * * * Rscript dataprocessing.R` cron.

## 4. Parity check vs the R app
For one use case (SNS-RWANDA), diff the normalized output against the R
`SNSRwandaSUMdata.csv`:
- Enumerator/household counts match.
- Per-(HHID, event) dates match the pivoted SUM columns.
- Issues view flags (bad ENID/HHID, out-of-sequence) match the R Issues tab.
- Event-completion grid colours match `dynamic_colorcodeS`.

## 5. Auth0 → roles migration
1. Keep Auth0 OIDC enabled. Existing users log in via Auth0; the social adapter
   snapshots their `eia_apps` claim into `User.legacy_eia_apps` + `auth0_sub`.
2. Map snapshots to memberships (VIEWER by default):
   ```bash
   python manage.py migrate_eia_apps --dry-run
   python manage.py migrate_eia_apps
   ```
3. In the admin, upgrade the right people to **Trial Coordinator** and
   **Quality Check** per use case; designate **Platform Admins** (superusers).

## 6. Parallel run, then cut over
- Run both apps against live ONA data for one cycle; compare dashboards.
- Flip DNS / reverse proxy to the Django app.
- Decommission the R container and its Azure-CSV cron.

## 7. Retire Auth0 (optional, later)
Once everyone has memberships and uses email login, unset `AUTH0_*` to disable the
OIDC bridge and remove the social apps. `auth0_sub` is retained for reconciliation.

## 8. Phase 2 (hybrid in-app editing) — unlocked, no schema change
The raw-vs-edited split (`Submission.raw_payload` immutable; `SubmissionValue.
current_value` authoritative) already supports app-authored/edited records. To
enable in-app authoring, add a form role and write values with
`source=REVIEWER_EDIT` — the review workflow and audit trail apply unchanged.
