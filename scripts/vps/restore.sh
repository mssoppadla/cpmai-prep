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

# Host-port overrides (BACKEND_HOST_PORT etc.) — same source as deploy.sh.
# Without this the health check below probes the compose DEFAULT port
# (8000) while prod actually publishes 8001, so a perfectly healthy
# backend read as "did not come back up" (2026-08-07 rollback).
[ -f .deploy.conf ] && { set -a; . ./.deploy.conf; set +a; }
BACKEND_PORT="${BACKEND_HOST_PORT:-8000}"

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
# the suffix .uploads.tar.gz instead of .sql.gz. Older backups (pre-PR-7)
# won't have this sidecar — skip with a warning.
#
# HARDENED after the 2026-08-07 incident, where the old sequence
# (wipe /app/uploads first, then `gunzip -c | tar -xzf` — a DOUBLE
# decompression that always fails — then print "✓ uploads restored"
# unconditionally) silently emptied prod's uploads during a rollback.
# Three rules now:
#   1. NEVER touch the live files until the archive has fully extracted
#      into a staging dir — a bad archive must be a no-op, not a wipe.
#   2. Refuse suspiciously small archives (an empty tar.gz is ~100 bytes;
#      backup.sh can produce one when uploads were already lost — restoring
#      it would just certify the loss).
#   3. Fail loudly. No success message unless the swap actually happened.
UPLOADS_TAR="${FILE%.sql.gz}.uploads.tar.gz"
if [ -f "$UPLOADS_TAR" ]; then
  TAR_BYTES=$(stat -c %s "$UPLOADS_TAR" 2>/dev/null || stat -f %z "$UPLOADS_TAR")
  if [ "${TAR_BYTES:-0}" -lt 1024 ]; then
    warn "uploads sidecar is only ${TAR_BYTES:-?} bytes — looks EMPTY."
    warn "Refusing to replace live uploads with it. If uploads are missing,"
    warn "restore from an older, full-size .uploads.tar.gz manually."
  else
    say "Restoring uploads from $(basename "$UPLOADS_TAR") ($(du -h "$UPLOADS_TAR" | cut -f1))..."
    # Stage → verify → swap. The tarball is already gzipped; feed it to
    # `tar -xzf -` directly (NO gunzip in front — that double-decompresses
    # and always fails).
    if $DC exec -T backend sh -c \
         'rm -rf /app/uploads.restore-tmp && mkdir -p /app/uploads.restore-tmp && tar -xzf - -C /app/uploads.restore-tmp' \
         < "$UPLOADS_TAR"; then
      RESTORED_COUNT=$($DC exec -T backend sh -c 'find /app/uploads.restore-tmp -type f | wc -l' | tr -dc 0-9)
      if [ "${RESTORED_COUNT:-0}" -gt 0 ]; then
        # Extraction verified — only now replace the live contents.
        # (/app/uploads is a volume mountpoint, so contents are moved
        # rather than the directory itself.)
        $DC exec -T backend sh -c \
          'mkdir -p /app/uploads && find /app/uploads -mindepth 1 -maxdepth 1 -exec rm -rf {} + && mv /app/uploads.restore-tmp/* /app/uploads/ 2>/dev/null; mv /app/uploads.restore-tmp/.[!.]* /app/uploads/ 2>/dev/null; rmdir /app/uploads.restore-tmp' \
          || die "uploads swap failed mid-way — check /app/uploads and /app/uploads.restore-tmp in the backend container"
        ok "uploads restored (${RESTORED_COUNT} files)"
      else
        $DC exec -T backend sh -c 'rm -rf /app/uploads.restore-tmp'
        warn "archive extracted but contains ZERO files — live uploads left untouched"
      fi
    else
      $DC exec -T backend sh -c 'rm -rf /app/uploads.restore-tmp' || true
      warn "uploads extraction FAILED — live uploads left untouched (archive may be corrupt)"
    fi
  fi
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
  if curl -fs "http://localhost:${BACKEND_PORT}/health" >/dev/null 2>&1; then
    ok "backend healthy after restore"; break
  fi
  sleep 1
  if [ "$i" = 60 ]; then die "backend did not come back up — check logs"; fi
done

echo
echo "✓ Restore complete from: $(basename "$FILE")"
echo "  pre-restore safety backup is in: ${BACKUP_DIR}"
echo "  if THIS restore was wrong, run: $0 ${BACKUP_DIR}/<latest pre-restore>.sql.gz"
