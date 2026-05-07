#!/usr/bin/env bash
# ==============================================================================
# deploy.sh — repeatable production deploy
# ==============================================================================
# Run this on every code change. It is the ONE command you run on the VPS
# after pushing to main:
#
#     ssh deploy@<vps>
#     cd /opt/cpmai-prep
#     git pull --ff-only
#     ./scripts/vps/deploy.sh
#
# Guarantees (in order):
#   1. Pre-deploy backup (so any rollback is one restore.sh away)
#   2. Build new images (with current frontend/.env.local public values)
#   3. Apply additive migrations (alembic upgrade head)
#   4. Run idempotent seeder (top up new defaults; never modifies existing)
#   5. Restart backend + frontend (rolling, NOT down/up — keeps DB & redis up)
#   6. Wait for /health to respond
#   7. Data-preservation guard (refuses to declare success if rows decreased)
#   8. 27-step smoke test
#
# The pre-deploy backup is the safety net — if anything in 3-8 fails, you
# can run ./scripts/vps/restore.sh on the snapshot from step 1.
#
# Usage:
#     ./scripts/vps/deploy.sh                  # pull from main, then deploy
#     SKIP_PULL=1 ./scripts/vps/deploy.sh      # deploy current checkout
#     SKIP_BACKUP=1 ./scripts/vps/deploy.sh    # only if a fresh backup exists
# ==============================================================================
set -euo pipefail

cd "$(dirname "$0")/../.."
APP_DIR="$(pwd)"
B=$'\033[1m'; G=$'\033[0;32m'; Y=$'\033[0;33m'; C=$'\033[0;36m'; X=$'\033[0m'
say()  { echo "${C}→${X} $*"; }
ok()   { echo "${G}✓${X} $*"; }
warn() { echo "${Y}!${X} $*" >&2; }
die()  { echo "✗ $*" >&2; exit 1; }

[ "$(id -u)" -ne 0 ] || die "Run as the deploy user, NOT root."
[ -f backend/.env ]            || die "backend/.env missing — did install_app.sh run?"
[ -f frontend/.env.local ]     || die "frontend/.env.local missing — did install_app.sh run?"
[ -f docker-compose.prod.yml ] || die "docker-compose.prod.yml missing — checkout broken?"
command -v docker >/dev/null   || die "docker not on PATH"
docker compose version >/dev/null 2>&1 || die "docker compose plugin missing"

DC="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

# Source frontend env so build args resolve at `compose build` time.
set -a; . ./frontend/.env.local; set +a

START_TS=$(date +%s)
START_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

# ------------------------------------------------------------------------------
# 1. Pull
# ------------------------------------------------------------------------------
if [ -z "${SKIP_PULL:-}" ]; then
  say "Pulling latest from origin..."
  git fetch --prune
  git pull --ff-only origin main || die "git pull --ff-only failed (uncommitted changes? non-FF history?)"
  ok "now at $(git rev-parse --short HEAD)"
else
  warn "SKIP_PULL=1 — deploying current checkout ($(git rev-parse --short HEAD))"
fi

NEW_SHA=$(git rev-parse --short HEAD)

if [ "$START_SHA" = "$NEW_SHA" ] && [ -z "${SKIP_PULL:-}" ]; then
  ok "Already at $NEW_SHA — nothing to deploy"
  # Still run the smoke test, because some changes are env-only (e.g. cron, secrets).
  say "Running smoke against current stack..."
  python3 scripts/smoke_admin_crud.py || die "smoke failed on no-op deploy — investigate"
  ok "Smoke green — exiting clean"
  exit 0
fi

# ------------------------------------------------------------------------------
# 2. Pre-deploy backup
# ------------------------------------------------------------------------------
if [ -z "${SKIP_BACKUP:-}" ]; then
  say "Pre-deploy backup..."
  ./scripts/vps/backup.sh "pre-deploy-${NEW_SHA}" || die "pre-deploy backup failed — refusing to proceed"
  ok "backup complete (rollback target: latest in /var/backups/cpmai-prep)"
else
  warn "SKIP_BACKUP=1 — proceeding without fresh backup"
fi

# ------------------------------------------------------------------------------
# 3. Snapshot for data-preservation check (BEFORE migrations / restart)
# ------------------------------------------------------------------------------
say "Snapshotting row counts of guarded tables..."
$DC exec -T backend python /app/../scripts/preserve_users_check.py snapshot 2>/dev/null \
  || python3 scripts/preserve_users_check.py snapshot \
  || die "snapshot failed"

# ------------------------------------------------------------------------------
# 4. Build new images (frontend bakes NEXT_PUBLIC_* from .env.local)
# ------------------------------------------------------------------------------
say "Building images..."
$DC build --pull
ok "images built"

# ------------------------------------------------------------------------------
# 5. Bring up new images (rolling — postgres / redis stay up)
# ------------------------------------------------------------------------------
say "Recreating backend + frontend with new images..."
$DC up -d --no-deps --build backend frontend
ok "containers up"

# ------------------------------------------------------------------------------
# 6. Wait for health
# ------------------------------------------------------------------------------
say "Waiting for backend health..."
for i in $(seq 1 60); do
  if curl -fs http://localhost:8000/health >/dev/null 2>&1; then
    ok "backend healthy"; break
  fi
  sleep 1
  if [ "$i" = 60 ]; then die "backend never became healthy — $DC logs backend"; fi
done

say "Waiting for frontend..."
for i in $(seq 1 30); do
  if curl -fs -o /dev/null -w "%{http_code}" http://localhost:3000 | grep -qE "^(200|301|302|307|308)$"; then
    ok "frontend responding"; break
  fi
  sleep 1
  if [ "$i" = 30 ]; then die "frontend never came up — $DC logs frontend"; fi
done

# ------------------------------------------------------------------------------
# 7. Migrations + seeder (additive, idempotent)
# ------------------------------------------------------------------------------
say "Running alembic upgrade head..."
$DC exec -T backend bash -c 'cd /app && alembic upgrade head'
ok "schema at head"

say "Running idempotent seeder..."
$DC exec -T backend python seeds/seed.py
ok "seeder done"

# ------------------------------------------------------------------------------
# 8. Data-preservation verify
# ------------------------------------------------------------------------------
say "Verifying no guarded table lost rows..."
python3 scripts/preserve_users_check.py verify || {
  warn "DATA PRESERVATION FAILED — a guarded table lost rows"
  warn "rollback with: ./scripts/vps/restore.sh /var/backups/cpmai-prep/<latest>.sql.gz"
  die "deploy aborted to protect user data"
}

# ------------------------------------------------------------------------------
# 9. Smoke
# ------------------------------------------------------------------------------
say "Running smoke against the upgraded stack..."
python3 scripts/smoke_admin_crud.py || {
  warn "smoke FAILED — site may be broken"
  warn "rollback with: ./scripts/vps/restore.sh /var/backups/cpmai-prep/<latest>.sql.gz"
  die "deploy aborted"
}

ELAPSED=$(( $(date +%s) - START_TS ))
echo
echo "${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
echo "${G}✓ Deploy complete${X}  ${START_SHA} → ${NEW_SHA}  in ${ELAPSED}s"
echo "${G}  data preserved · migrations applied · smoke green${X}"
echo "${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
