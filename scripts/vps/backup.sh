#!/usr/bin/env bash
# ==============================================================================
# backup.sh — Postgres + .env + uploads snapshot
# ==============================================================================
# Ways this runs:
#   • Daily cron (installed by install_app.sh) at 02:30 server time
#   • Pre-deploy from deploy.sh, with a "pre-deploy-<sha>" tag
#   • Manually:   ./scripts/vps/backup.sh
#                 ./scripts/vps/backup.sh "before-rzp-key-rotation"
#
# Output:  /var/backups/cpmai-prep/<timestamp>__<tag>.sql.gz
#          + a .env tar in the same dir, same timestamp
#          + an uploads tar (CMS/LMS file attachments) in the same dir
#
# Retention: keeps last 30 daily backups + ALL pre-deploy backups for 14 days.
# Pre-deploy backups stay even past 30 days because they protect the rollback
# window.
# ==============================================================================
set -euo pipefail

cd "$(dirname "$0")/../.."
APP_DIR="$(pwd)"
BACKUP_DIR="/var/backups/cpmai-prep"
TAG="${1:-daily}"
TS=$(date -u +%Y%m%dT%H%M%SZ)
SQL_FILE="${BACKUP_DIR}/${TS}__${TAG}.sql.gz"
ENV_FILE="${BACKUP_DIR}/${TS}__${TAG}.env.tar.gz"
UPLOADS_FILE="${BACKUP_DIR}/${TS}__${TAG}.uploads.tar.gz"

say()  { printf '==> %s\n' "$*"; }
ok()   { printf '  ✓ %s\n' "$*"; }
warn() { printf '  ! %s\n' "$*" >&2; }
die()  { printf '  ✗ %s\n' "$*" >&2; exit 1; }

[ -d "$BACKUP_DIR" ] || die "$BACKUP_DIR missing — run provision.sh"
[ -w "$BACKUP_DIR" ] || die "$BACKUP_DIR not writable by $(whoami)"

DC="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
$DC ps postgres --status running --quiet | grep -q . \
  || die "postgres container is not running — start the stack first"

# ------------------------------------------------------------------------------
# 1. Postgres dump (custom format for fast parallel restore + plain SQL gzip)
# ------------------------------------------------------------------------------
say "Dumping cpmai_prep → ${SQL_FILE}"
# pg_dump runs INSIDE the container, then we stream gzipped SQL out via stdout.
$DC exec -T postgres \
  pg_dump -U cpmai -d cpmai_prep --no-owner --no-privileges --clean --if-exists \
  | gzip -9 > "${SQL_FILE}.partial"
mv "${SQL_FILE}.partial" "$SQL_FILE"
SIZE=$(du -h "$SQL_FILE" | cut -f1)
ok "sql backup ${SIZE}"

# ------------------------------------------------------------------------------
# 2. Env / config snapshot (so a restore can recover cleanly)
# ------------------------------------------------------------------------------
say "Archiving env files → ${ENV_FILE}"
tar -czf "$ENV_FILE" \
  --transform 's,^,env-snapshot/,' \
  backend/.env \
  frontend/.env.local \
  2>/dev/null || warn "some env files missing (skipped)"
chmod 0600 "$ENV_FILE"
ok "env snapshot stored"

# ------------------------------------------------------------------------------
# 3. Uploads snapshot (CMS / LMS file attachments)
# ------------------------------------------------------------------------------
# Uploads live in the `cpmai-uploads` named docker volume mounted at
# /app/uploads inside the backend container (see docker-compose.yml).
# Stream a tarball straight out of the running container so we don't
# need to know the host-side volume mountpoint. If the directory is
# empty (fresh install, no uploads yet), tar still produces a valid
# empty archive — restore.sh handles that case as a no-op.
say "Archiving uploads volume → ${UPLOADS_FILE}"
if $DC exec -T backend sh -c 'test -d /app/uploads' 2>/dev/null; then
  $DC exec -T backend tar -czf - -C /app/uploads . > "${UPLOADS_FILE}.partial" \
    && mv "${UPLOADS_FILE}.partial" "$UPLOADS_FILE" \
    || { rm -f "${UPLOADS_FILE}.partial"; warn "uploads tar failed (continuing)"; }
  if [ -f "$UPLOADS_FILE" ]; then
    # Uploads can include signed PDFs / screenshots with personal data —
    # match the env tar's 0600 so /var/backups is read-protected even
    # if a different system user can browse the dir.
    chmod 0600 "$UPLOADS_FILE"
    USIZE=$(du -h "$UPLOADS_FILE" | cut -f1)
    ok "uploads snapshot ${USIZE}"
  fi
else
  warn "backend has no /app/uploads dir (skipped) — is the cpmai-uploads volume mounted?"
fi

# ------------------------------------------------------------------------------
# 4. Retention
# ------------------------------------------------------------------------------
# Daily backups: keep 30 most recent
# Pre-deploy:   keep all from last 14 days, prune older than 14
say "Pruning old backups..."
# Each block is wrapped in `|| true` so an empty-pattern (no matching files)
# doesn't kill the whole script under `set -e + pipefail`. The whole
# retention pass runs in a subshell with set +e so individual commands
# can fail noisily without aborting the surrounding deploy.
(
  set +e
  # Daily — keep 30 most recent
  ls -1t "$BACKUP_DIR"/*__daily.sql.gz 2>/dev/null \
    | tail -n +31 | xargs -r rm -f
  ls -1t "$BACKUP_DIR"/*__daily.env.tar.gz 2>/dev/null \
    | tail -n +31 | xargs -r rm -f
  ls -1t "$BACKUP_DIR"/*__daily.uploads.tar.gz 2>/dev/null \
    | tail -n +31 | xargs -r rm -f
  # Pre-deploy older than 14 days
  find "$BACKUP_DIR" -maxdepth 1 -name '*__pre-deploy-*' -mtime +14 -print -delete 2>/dev/null \
    | sed 's/^/  pruned /'
  # Manual / arbitrary tags older than 30 days
  find "$BACKUP_DIR" -maxdepth 1 \
    ! -name '*__daily*' ! -name '*__pre-deploy-*' \
    -name '*.sql.gz' -mtime +30 -print -delete 2>/dev/null \
    | sed 's/^/  pruned /'
  exit 0
)

ok "retention applied"
echo
echo "Backup OK: ${SQL_FILE}"
echo "Restore : ./scripts/vps/restore.sh ${SQL_FILE}"
