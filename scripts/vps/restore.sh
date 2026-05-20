#!/usr/bin/env bash
# ==============================================================================
# restore.sh — restore cpmai_prep from a backup file
# ==============================================================================
# DESTRUCTIVE: drops the current database before restoring. Use it when:
#   • A bad deploy lost data and you want to roll back
#   • You're cloning prod data into a staging VPS
#   • You're restoring after a server rebuild
#
# Usage:
#     ./scripts/vps/restore.sh /var/backups/cpmai-prep/<file>.sql.gz
#     ./scripts/vps/restore.sh latest         # uses the newest backup
#
# Safety:
#   1. Asks for confirmation before dropping data (set CONFIRM=1 to skip).
#   2. Takes a "pre-restore" backup BEFORE dropping anything (so you can
#      undo the restore if it was the wrong file).
#   3. Restarts backend after restore so the connection pool is fresh.
# ==============================================================================
set -euo pipefail

cd "$(dirname "$0")/../.."
APP_DIR="$(pwd)"
BACKUP_DIR="/var/backups/cpmai-prep"
say()  { printf '==> %s\n' "$*"; }
ok()   { printf '  ✓ %s\n' "$*"; }
warn() { printf '  ! %s\n' "$*" >&2; }
die()  { printf '  ✗ %s\n' "$*" >&2; exit 1; }

[ "${1:-}" ] || die "Usage: $0 <backup.sql.gz | latest>"

if [ "$1" = "latest" ]; then
  FILE=$(ls -1t "$BACKUP_DIR"/*.sql.gz 2>/dev/null | head -1)
  [ -n "$FILE" ] || die "no backups found in $BACKUP_DIR"
else
  FILE="$1"
fi
[ -f "$FILE" ] || die "backup file not found: $FILE"

DC="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
$DC ps postgres --status running --quiet | grep -q . \
  || die "postgres container not running — start the stack first"

# ------------------------------------------------------------------------------
# 1. Confirmation
# ------------------------------------------------------------------------------
echo
warn "About to RESTORE the database from:"
warn "  ${FILE}"
warn "  ($(du -h "$FILE" | cut -f1), modified $(stat -c %y "$FILE" 2>/dev/null || stat -f %Sm "$FILE"))"
warn ""
warn "This will DROP the current cpmai_prep database and replace it."
warn "All data created since this backup will be LOST (a pre-restore"
warn "snapshot is taken first, so this is reversible)."
echo

if [ -z "${CONFIRM:-}" ]; then
  read -rp "Type RESTORE to proceed: " ans
  [ "$ans" = "RESTORE" ] || die "aborted"
fi

# ------------------------------------------------------------------------------
# 2. Pre-restore safety backup
# ------------------------------------------------------------------------------
say "Taking pre-restore backup of current state (in case this is a mistake)..."
./scripts/vps/backup.sh "pre-restore-$(date +%s)" || die "pre-restore backup failed — refusing to proceed"

# ------------------------------------------------------------------------------
# 3. Restore
# ------------------------------------------------------------------------------
# Our pg_dump uses --clean --if-exists, so the dump itself drops + recreates
# objects. We just need to feed it back in via psql.
say "Restoring from $(basename "$FILE")..."
gunzip -c "$FILE" | $DC exec -T postgres psql -U cpmai -d cpmai_prep -v ON_ERROR_STOP=1 \
  || die "restore failed — DB may be in inconsistent state, restore from pre-restore backup"
ok "data restored"

# ------------------------------------------------------------------------------
# 4. Restore uploads (CMS / LMS file attachments) — sidecar tarball
# ------------------------------------------------------------------------------
# backup.sh writes the matching uploads archive next to the SQL dump with
# the suffix .uploads.tar.gz instead of .sql.gz. If it exists, replace the
# /app/uploads volume contents with the snapshot. Wiping first prevents
# stray orphan files from a newer state hanging around after a rollback.
# Older backups (pre-PR-7) won't have this sidecar — skip silently.
UPLOADS_TAR="${FILE%.sql.gz}.uploads.tar.gz"
if [ -f "$UPLOADS_TAR" ]; then
  say "Restoring uploads from $(basename "$UPLOADS_TAR")..."
  $DC exec -T backend sh -c 'mkdir -p /app/uploads && find /app/uploads -mindepth 1 -delete' \
    || warn "could not clear /app/uploads before restore (may have stale files)"
  gunzip -c "$UPLOADS_TAR" | $DC exec -T backend tar -xzf - -C /app/uploads \
    || warn "uploads restore failed — file attachments may be missing"
  ok "uploads restored"
else
  warn "no uploads sidecar at $UPLOADS_TAR (skipped — backup may predate uploads support)"
fi

# ------------------------------------------------------------------------------
# 5. Bring backend up to head (in case the backup is from an older schema)
# ------------------------------------------------------------------------------
say "Running alembic upgrade head against restored DB..."
$DC exec -T backend bash -c 'cd /app && alembic upgrade head' \
  || warn "alembic upgrade failed — restored data may need manual schema fixup"

# ------------------------------------------------------------------------------
# 5. Restart backend so the connection pool is fresh
# ------------------------------------------------------------------------------
say "Restarting backend..."
$DC restart backend
for i in $(seq 1 60); do
  if curl -fs http://localhost:8000/health >/dev/null 2>&1; then
    ok "backend healthy after restore"; break
  fi
  sleep 1
  if [ "$i" = 60 ]; then die "backend did not come back up — check logs"; fi
done

echo
echo "✓ Restore complete from: $(basename "$FILE")"
echo "  pre-restore safety backup is in: ${BACKUP_DIR}"
echo "  if THIS restore was wrong, run: $0 ${BACKUP_DIR}/<latest pre-restore>.sql.gz"
