# Sandbox verification runbook (collection + provisioning + AI)

Run this once on staging against a real ODK Central / ONA / Kobo **sandbox**
project. It exercises the three integrations that only work with live
credentials: **form publish**, **collector auto-provisioning**, and **AI form
drafting**. Everything ships gated OFF until these pass.

## Environment
```bash
# staging .env — never commit real values
ONA_TOKEN=...                    # or a per-project token on the DataSource
FIELD_ENCRYPTION_KEY=...         # Fernet key for encrypted DataSource creds
AUTO_PROVISION_COLLECTORS=false  # keep OFF until step 4 passes
WRITEBACK_ENABLED=false          # keep OFF until step 5 passes
FORM_AI_API_KEY=                 # only for step 6
FORM_AI_ENABLED=false
```

## 0. Migrate + seed
```bash
python manage.py migrate
python manage.py import_vocabulary        # Terminag (~595 vars / 1946 values)
python manage.py bootstrap_admin          # first Platform Admin
```
✔ `/manage/vocabulary/` lists the terms.

## 1. Connect a project to its server
Onboard a project (UI: **Manage → Onboard**) or seed a `DataSource`
(backend + token + `config.project_id`), then:
```bash
python manage.py test_connection          # backend reachable for every project
```
✔ No errors; the project's forms are discoverable.

## 2. Author + publish a form  (Tier 1 / 2)
UI: **Design forms → Build a form** (or **Upload XLSForm**) → pick the sandbox
project → **Save & publish to server**.
✔ Form appears in ODK/ONA; a `FormDefinition` is created; the draft is *Published*.

## 3. Pull submissions
Submit 1–2 test records in ODK Collect / Enketo, then:
```bash
python manage.py sync_project <CODE>      # or --all
```
✔ Records show under the project **Data** tab; enumerators/units auto-created.

## 4. Grant a user + verify provisioning  (gated)
```bash
python manage.py provision_collectors --project <CODE> --dry-run   # preview
# then set AUTO_PROVISION_COLLECTORS=true and grant a user in Team & access,
# or backfill existing grants:
python manage.py provision_collectors --project <CODE>
```
✔ **Manage → Server accounts** shows `ACTIVE` / `LINKED`; the account exists on
the server. Failures record as `FAILED` and never block the grant.

## 5. Review workflow + write-back
In the project **Review** tab: endorse → validate → decline a record.
```bash
python manage.py writeback_test           # dry-run; add --commit + WRITEBACK_ENABLED=true to push
```
✔ Transitions land; **Review log** shows the audit trail; write-back dry-run OK.

## 6. AI drafting  (optional, Tier 3)
```bash
# FORM_AI_API_KEY set, FORM_AI_ENABLED=true
python manage.py test_form_ai --draft
```
✔ "AI service reachable" + a sample form drafts.

## Rollback
All local DB state is disposable. Server-side, delete the test form in ODK/ONA
and remove the test app-user; set `AUTO_PROVISION_COLLECTORS=false` to stop
further mirroring.

## Enable in production only after
- Steps 1–3 pass (publish + sync round-trips work).
- Step 4 passes on a throwaway user before flipping `AUTO_PROVISION_COLLECTORS`.
- Step 5 write-back verified against the sandbox before `WRITEBACK_ENABLED=true`.
- Step 6 only if AI drafting is wanted; it never auto-publishes.
