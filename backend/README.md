# EiA2030 Data Collection Monitoring Tool (Django)

Python/Django + Postgres redesign of the R Shiny `dc_dashboard`. See the build
plan for the full architecture. This replaces the hardcoded R pipeline with a
**config-driven** ingestion + validation engine, adds **registration + RBAC**
(Platform Admin / Trial Coordinator / Quality Check-Agronomist / Viewer), and a
**review workflow** (decline / request edit / edit) with a full audit trail.

## Layout

```
eia_dcmt/         Django project (settings split: base/dev/stg/prod/test, celery, urls)
apps/
  common/         Base models (UUID + timestamps), healthcheck, plugin contract
  accounts/       Custom email User, registration/approval, Auth0 migration fields
  rbac/           Role + UseCaseMembership (per-use-case scoping), user_can facade
  usecases/       UseCase + config models (forms, field mappings, event schedule)
  config_admin/   YAML <-> DB round-trip + Admin UI for authoring use cases
  ingestion/      ONA client + generic normalize/pivot/dedup engine + Celery tasks
  submissions/    Submission (raw, immutable) + SubmissionValue (authoritative/edited)
  review/         Review state machine + append-only ReviewAction audit log
  validation/     Pluggable rule engine -> ValidationFlag
  dashboards/      HTMX tabs + Plotly/Folium (feature parity with the R app)
  api/            DRF read + review-action endpoints
plugins/          Optional per-use-case Python hooks (e.g. BioSSA)
config/usecases/  Versioned YAML seeds (one file == one use case)
```

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Postgres + Redis via Docker (or point DATABASE_URL at your own):
docker compose up -d db redis
cp .env.example .env

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Quality gates

```bash
pytest            # unit tests (SQLite, fast)
ruff check .      # lint
mypy .            # types
```

Health probe: `GET /healthz/`.
