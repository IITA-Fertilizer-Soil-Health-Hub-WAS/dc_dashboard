# Backup, disaster recovery & safe upgrades

Addresses the database-corruption, data-loss, and upgrade/migration risks
raised in the ODK-Central limitations review. None of these are ODK- or
CSWeb-specific — they are ops discipline that any Postgres/SQL stack needs.
The rule: **a backup you have never restored is not a backup.**

## What to back up

| Asset | Where | How |
|-------|-------|-----|
| Fieldbase database | `backend-db-1` Postgres (`eia_dcmt`) | `pg_dump` (nightly) |
| ODK Central database | Central's Postgres (`odk`) | `pg_dump` (nightly) |
| Submitted media / attachments | Central blob store / `media/` volume | volume snapshot or `rclone` |
| Secrets | `.env` files (NOT in git) | encrypted copy in a password manager / vault |
| Config-as-data | project YAML, XLSForms | already in git; keep exports too |

## Automated nightly backups

Use [`scripts/pg_backup.sh`](../scripts/pg_backup.sh) — it dumps each database
(custom compressed format), verifies the dump isn't empty, keeps 14 days
locally, and can sync off-box.

```bash
sudo mkdir -p /opt/fieldbase && sudo cp -r scripts /opt/fieldbase/
sudo tee /etc/cron.d/fieldbase-backup >/dev/null <<'CRON'
0 2 * * * root PGPASSWORD=... OFFSITE_RCLONE=s3:fieldbase-backups /opt/fieldbase/scripts/pg_backup.sh >> /var/log/fieldbase-backup.log 2>&1
CRON
```

**3-2-1 rule:** ≥3 copies, on 2 media, 1 off-site. The `OFFSITE_RCLONE` sync is
what saves you when the host's disk dies. Also enable **WAL archiving /
point-in-time recovery** on the Central DB for anything close to real-time RPO.

## Restore drill (run monthly — this is the part everyone skips)

Restore into a *throwaway* container and confirm row counts, never straight to
prod:

```bash
# 1. spin up a scratch Postgres
docker run -d --name restore-test -e POSTGRES_PASSWORD=x postgres:16
# 2. restore the latest Fieldbase dump
gunzip -c /var/backups/fieldbase/fieldbase-eia_dcmt-*.dump.gz \
  | docker exec -i restore-test pg_restore -U postgres -d postgres --clean --no-owner
# 3. sanity-check
docker exec restore-test psql -U postgres -c \
  "select count(*) from submissions_submission;"
docker rm -f restore-test
```

Record the date + row counts each month. A restore that fails in a drill is a
problem you fix on a Tuesday, not during an outage.

## Safe server upgrades (ODK Central or Fieldbase)

Never upgrade in place without a tested path out:

1. **Backup first** — run `pg_backup.sh` and confirm the dump size.
2. **Snapshot** the VM / volumes if the host supports it (instant rollback).
3. **Stage** — apply the upgrade on a staging copy, run `manage.py migrate`
   there, and smoke-test (log in, open a project, run a sync, run validation).
4. **Read the release notes** for breaking DB migrations before prod.
5. **Maintenance window** — stop writers, upgrade, `migrate`, verify, re-open.
6. **Rollback plan written down** *before* you start: restore snapshot, or
   restore the dump into the previous image tag.

For Fieldbase specifically, migrations are tested in CI and `manage.py migrate`
runs on container start — but still take a dump before a prod deploy.

## Preventing corruption in the first place

- **Never `kill -9` / hard-stop the DB.** Use `docker compose stop` (graceful).
- **Watch disk** — a full disk is the #1 cause of Postgres corruption. Alert at
  80%. Media grows fast; put it on its own volume/NAS.
- **UPS / managed host** so sudden power loss doesn't tear a write.
- **`autovacuum` on** (default) and don't disable it.
- **Checksums**: initialise the Central DB with `--data-checksums` so silent
  disk errors are detected early.

## Form-update discipline (avoid data loss on XLSForm changes)

Changing a live form's fields can strand old submissions. Rules that reduce the
blast radius:

- **Never rename or delete a field that has data** — add a new one instead.
- **Bump the form version** on every change (ODK requires it) so submissions
  are traceable to the schema that produced them.
- After a form change, re-run **Import fields & names** in Fieldbase so the
  field list and validation rules stay aligned with the live form.
- Keep each published XLSForm in git (Fieldbase's form builder already versions
  drafts).

## Export / transformation safety

Corruption usually happens *after* export (Excel/CSV round-trips), not in the
DB. Prefer the platform's own reconciliation (reference datasets, validation
rules, coverage report) over manual spreadsheet editing. When you must export,
export from Fieldbase's audited path and keep the raw dump as the source of
truth.
