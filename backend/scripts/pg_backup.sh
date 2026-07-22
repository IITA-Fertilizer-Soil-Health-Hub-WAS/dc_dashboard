#!/usr/bin/env bash
# Nightly Postgres backup for the Fieldbase + ODK Central databases.
#
# Dumps each database with pg_dump (custom format, compressed), keeps N days of
# local copies, and (optionally) syncs them off-box. Designed to run from cron
# on the docker host. Safe to run while the app is up — pg_dump is consistent.
#
# Usage:
#   ./pg_backup.sh                       # uses the defaults below
#   BACKUP_DIR=/mnt/backups ./pg_backup.sh
#
# Cron (02:00 daily), logging to syslog:
#   0 2 * * * /opt/fieldbase/scripts/pg_backup.sh >> /var/log/fieldbase-backup.log 2>&1
set -euo pipefail

# --- Config (override via environment) --------------------------------------
BACKUP_DIR="${BACKUP_DIR:-/var/backups/fieldbase}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
# Fieldbase DB (matches docker-compose.yml defaults)
FB_CONTAINER="${FB_CONTAINER:-backend-db-1}"
FB_DB="${FB_DB:-eia_dcmt}"
FB_USER="${FB_USER:-eia}"
# ODK Central DB — set these if Central runs on the same host (else run this
# script there too). Leave ODK_CONTAINER empty to skip.
ODK_CONTAINER="${ODK_CONTAINER:-}"
ODK_DB="${ODK_DB:-odk}"
ODK_USER="${ODK_USER:-odk}"
# Optional off-box sync target, e.g. an rclone remote or an rsync path.
OFFSITE_RCLONE="${OFFSITE_RCLONE:-}"          # e.g. "s3remote:fieldbase-backups"

stamp="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

dump() {  # <container> <db> <user> <label>
  local container="$1" db="$2" user="$3" label="$4"
  local out="$BACKUP_DIR/${label}-${db}-${stamp}.dump"
  echo "[$(date -Is)] dumping $label/$db -> $out"
  docker exec -e PGPASSWORD="${PGPASSWORD:-}" "$container" \
    pg_dump -U "$user" -Fc --no-owner "$db" > "$out"
  # Fail loudly if the dump is suspiciously small (empty/failed).
  local size; size=$(stat -c%s "$out" 2>/dev/null || stat -f%z "$out")
  if [ "$size" -lt 1024 ]; then
    echo "ERROR: $out is only ${size} bytes — backup likely failed" >&2
    exit 1
  fi
  gzip -f "$out"
}

dump "$FB_CONTAINER" "$FB_DB" "$FB_USER" "fieldbase"
if [ -n "$ODK_CONTAINER" ]; then
  dump "$ODK_CONTAINER" "$ODK_DB" "$ODK_USER" "odkcentral"
fi

# Prune old local backups.
find "$BACKUP_DIR" -name '*.dump.gz' -mtime "+${RETENTION_DAYS}" -delete

# Off-box copy (3-2-1 rule: keep a copy somewhere the host can't take down).
if [ -n "$OFFSITE_RCLONE" ]; then
  echo "[$(date -Is)] syncing to $OFFSITE_RCLONE"
  rclone copy "$BACKUP_DIR" "$OFFSITE_RCLONE" --include '*.dump.gz'
fi

echo "[$(date -Is)] backup complete"
