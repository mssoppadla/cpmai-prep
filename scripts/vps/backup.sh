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

# ── Self-verification (every backup, every time) ─────────────────────
# A corrupt or truncated dump discovered at RESTORE time is a disaster;
# discovered now it's a re-run. Three checks:
#   1. gzip integrity — catches truncation/corruption on disk
#   2. plausible size — an empty-DB dump is ~1KB; ours is many MB
#   3. row-count manifest — per-table counts recorded NEXT to the dump,
#      so any future restore can be verified against what was saved
gunzip -t "$SQL_FILE" || die "BACKUP CORRUPT: $SQL_FILE fails gzip check — do not trust this backup"
SQL_BYTES=$(stat -c %s "$SQL_FILE" 2>/dev/null || stat -f %z "$SQL_FILE")
if [ "${SQL_BYTES:-0}" -lt 100000 ]; then
  warn "═══════════════════════════════════════════════════════════"
  warn "sql backup is only ${SQL_BYTES} bytes — suspiciously small for"
  warn "a live database. Verify before trusting this backup."
  warn "═══════════════════════════════════════════════════════════"
fi
ok "sql backup verified (gzip integrity OK)"

# Custom-format dump alongside the plain SQL: enables SINGLE-TABLE
# restore (pg_restore --table=X) without touching the rest of the DB —
# the plain .sql.gz can only do all-or-nothing. See
# docs/backup-rollback-runbook.md scenario C.
DUMP_FILE="${BACKUP_DIR}/${TS}__${TAG}.dump"
$DC exec -T postgres \
  pg_dump -U cpmai -d cpmai_prep --no-owner --no-privileges -Fc \
  > "${DUMP_FILE}.partial" \
  && mv "${DUMP_FILE}.partial" "$DUMP_FILE" \
  && chmod 0600 "$DUMP_FILE" \
  && ok "custom-format dump (single-table restore capable) $(du -h "$DUMP_FILE" | cut -f1)" \
  || { rm -f "${DUMP_FILE}.partial"; warn "custom-format dump failed — full restore still available via .sql.gz"; }

# Row-count manifest — every table, recorded at backup time. ANALYZE
# first: n_live_tup is a planner ESTIMATE and reads 0 on stale stats
# (observed in sandbox: real rows, manifest said 0 — a misleading
# manifest is worse than none). ANALYZE is seconds on this DB size.
COUNTS_FILE="${BACKUP_DIR}/${TS}__${TAG}.counts.txt"
$DC exec -T postgres psql -U cpmai -d cpmai_prep -q -c "ANALYZE" 2>/dev/null || true
$DC exec -T postgres psql -U cpmai -d cpmai_prep -At -c \
  "SELECT relname || '=' || n_live_tup FROM pg_stat_user_tables ORDER BY relname" \
  > "$COUNTS_FILE" 2>/dev/null \
  && ok "row-count manifest ($(wc -l < "$COUNTS_FILE" | tr -d ' ') tables)" \
  || warn "manifest failed (non-fatal)"

# ------------------------------------------------------------------------------
# 2. Env / config snapshot (so a restore can recover cleanly)
# ------------------------------------------------------------------------------
say "Archiving env files → ${ENV_FILE}"
# System-level config rides in the same tar: the LIVE Caddyfile (the
# repo copy has drifted from /etc/caddy before — row 39; the live file
# is the truth about ports/hosts) and the deploy user's crontab. Both
# are copied into a temp dir first so tar gets stable relative paths;
# unreadable/missing ones are skipped LOUDLY, never silently.
SYSCONF_DIR="$(mktemp -d)"
if [ -r /etc/caddy/Caddyfile ]; then
  cp /etc/caddy/Caddyfile "$SYSCONF_DIR/Caddyfile.live" \
    || warn "could not copy live Caddyfile"
else
  warn "live Caddyfile not readable at /etc/caddy/Caddyfile (skipped)"
fi
crontab -l > "$SYSCONF_DIR/crontab.txt" 2>/dev/null \
  || warn "no crontab for $(whoami) (skipped)"
tar -czf "$ENV_FILE" \
  --transform 's,^,env-snapshot/,' \
  backend/.env \
  frontend/.env.local \
  -C "$SYSCONF_DIR" . \
  2>/dev/null || warn "some env/config files missing (skipped)"
rm -rf "$SYSCONF_DIR"
chmod 0600 "$ENV_FILE"
ok "env + system-config snapshot stored"

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
    # An empty uploads dir produces a ~100-byte archive. That's valid tar
    # but almost certainly means the uploads were LOST (as on 2026-08-07,
    # when a broken restore wiped them and the next pre-deploy backup
    # dutifully archived the emptiness). Shout — a later restore of this
    # file would just certify the loss. restore.sh refuses <1KB archives
    # for the same reason.
    UBYTES=$(stat -c %s "$UPLOADS_FILE" 2>/dev/null || stat -f %z "$UPLOADS_FILE")
    if [ "${UBYTES:-0}" -lt 1024 ]; then
      warn "═══════════════════════════════════════════════════════════"
      warn "uploads snapshot is only ${UBYTES} bytes — /app/uploads looks"
      warn "EMPTY. If that's unexpected, restore uploads from an older"
      warn "full-size .uploads.tar.gz BEFORE trusting this backup."
      warn "═══════════════════════════════════════════════════════════"
    else
      ok "uploads snapshot ${USIZE}"
    fi
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
  # Daily — keep 30 most recent sql/env (small), but only 7 uploads
  # tarballs: at ~2 GB each, 30 of them is ~60 GB of near-identical
  # archives — THE disk eater found on 2026-08-07 (76/96 GB used while
  # the app itself needs ~2 GB). Uploads change rarely; a week of
  # dailies plus the pre-deploy copies below is ample coverage.
  ls -1t "$BACKUP_DIR"/*__daily.sql.gz 2>/dev/null \
    | tail -n +31 | xargs -r rm -f
  ls -1t "$BACKUP_DIR"/*__daily.env.tar.gz 2>/dev/null \
    | tail -n +31 | xargs -r rm -f
  ls -1t "$BACKUP_DIR"/*__daily.uploads.tar.gz 2>/dev/null \
    | tail -n +8 | xargs -r rm -f
  # Custom-format dumps + manifests follow the daily-sql retention (30)
  ls -1t "$BACKUP_DIR"/*__daily.dump 2>/dev/null \
    | tail -n +31 | xargs -r rm -f
  ls -1t "$BACKUP_DIR"/*__daily.counts.txt 2>/dev/null \
    | tail -n +31 | xargs -r rm -f
  # Pre-deploy older than 14 days
  find "$BACKUP_DIR" -maxdepth 1 -name '*__pre-deploy-*' -mtime +14 -print -delete 2>/dev/null \
    | sed 's/^/  pruned /'
  # Pre-deploy UPLOADS tarballs additionally capped at the 5 most recent
  # regardless of age: at ~2 GB each, a burst of deploys can eat the disk
  # inside the 14-day window (2026-08-07: 67% → 81% in one day). The
  # matching .sql.gz files stay the full 14 days — they're small and
  # they're the actual rollback target; uploads rarely change per-deploy.
  ls -1t "$BACKUP_DIR"/*__pre-deploy-*.uploads.tar.gz 2>/dev/null \
    | tail -n +6 | xargs -r rm -f
  # Manual / arbitrary tags older than 30 days — ALL three suffixes.
  # (Was .sql.gz only, which stranded 2 GB uploads tarballs forever.)
  find "$BACKUP_DIR" -maxdepth 1 \
    ! -name '*__daily*' ! -name '*__pre-deploy-*' \
    \( -name '*.sql.gz' -o -name '*.env.tar.gz' -o -name '*.uploads.tar.gz' \
       -o -name '*.dump' -o -name '*.counts.txt' \) \
    -mtime +30 -print -delete 2>/dev/null \
    | sed 's/^/  pruned /'
  exit 0
)

ok "retention applied"
echo
echo "Backup OK: ${SQL_FILE}"
echo "Restore : ./scripts/vps/restore.sh ${SQL_FILE}"
