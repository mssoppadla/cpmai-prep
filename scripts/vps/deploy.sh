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

# When deploy.sh itself updates this script (via git pull below), the bash
# interpreter has already loaded the body running NOW — file changes on
# disk don't reach the running process. So if the running deploy.sh is
# from BEFORE the SMOKE_ADMIN backfill (commit 45918ed), this run won't
# auto-bootstrap. Re-running deploy.sh once it's pulled fixes it; the
# backfill block below also force-restarts the backend so the new env
# vars are picked up immediately on no-op-path runs.

# Source frontend env so build args resolve at `compose build` time.
set -a; . ./frontend/.env.local; set +a

# Source .deploy.conf — sets PROD_DOMAIN + host-port overrides. The
# docker-compose.prod.yml interpolates BACKEND_HOST_PORT / FRONTEND_HOST_PORT,
# and our health probes / smoke target read PROD_DOMAIN.
[ -f .deploy.conf ] && { set -a; . ./.deploy.conf; set +a; }
[ -n "${PROD_DOMAIN:-}" ] || die ".deploy.conf missing PROD_DOMAIN — run install_app.sh first"
: "${BACKEND_HOST_PORT:=8000}"
: "${FRONTEND_HOST_PORT:=3000}"
export BACKEND_HOST_PORT FRONTEND_HOST_PORT

# Backfill SMOKE_ADMIN_* into backend/.env if it predates the smoke-account
# split. The seeder (and the smoke) only consult these if they're set, so
# this is safe to run on every deploy: it's a true no-op once the lines
# already exist.
if ! grep -q '^SMOKE_ADMIN_EMAIL=' backend/.env; then
  say "Backfilling SMOKE_ADMIN_* into backend/.env (one-time)..."
  SMOKE_PW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
  cat >> backend/.env <<EOF

# Smoke / CI test super-admin — separate from BOOTSTRAP_ADMIN so rotating
# the operator password never breaks the deploy gate. Auto-added by
# scripts/vps/deploy.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ).
SMOKE_ADMIN_EMAIL=smoke-admin@${PROD_DOMAIN}
SMOKE_ADMIN_PASSWORD=${SMOKE_PW}
EOF
  chmod 0600 backend/.env
  unset SMOKE_PW
  # The backend container's process env is sealed at start — it won't see
  # the new SMOKE_ADMIN_* lines until restart. Do that now so the seeder
  # and login probes pick them up later in this same run.
  if $DC ps backend --status running --quiet 2>/dev/null | grep -q .; then
    say "Restarting backend so new env vars take effect..."
    $DC restart backend
    for i in $(seq 1 30); do
      if curl -fs -H "Host: api.${PROD_DOMAIN}" \
            "http://localhost:${BACKEND_HOST_PORT}/health" >/dev/null 2>&1; then
        break
      fi
      sleep 1
    done
  fi
  ok "smoke admin credentials added; backend restarted"
fi

# Ensure the bind-mounted logs dir is writable by the container's app user
# (uid 999, set by backend Dockerfile's `useradd -r`). Idempotent: chown is
# fine on a directory that already has the right owner.
mkdir -p backend/logs
sudo chown 999:999 backend/logs 2>/dev/null || true
sudo chmod 0755 backend/logs 2>/dev/null || true

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

SMOKE_BASE_URL="https://api.${PROD_DOMAIN}/api/v1"

if [ "$START_SHA" = "$NEW_SHA" ] && [ -z "${SKIP_PULL:-}" ]; then
  ok "Already at $NEW_SHA — no code change"
  # Even on a no-op deploy we re-run the idempotent seeder, because seed
  # JSON content can change between deploys (e.g. new default FAQs) without
  # any other code touching that path. Cheap, safe, never overwrites.
  say "Running idempotent seeder against current stack..."
  $DC exec -T backend python seeds/seed.py \
    || warn "seeder hiccup on no-op path — re-run manually if needed"
  say "Running smoke against $SMOKE_BASE_URL..."
  BASE_URL="$SMOKE_BASE_URL" python3 scripts/smoke_admin_crud.py \
    || die "smoke failed on no-op deploy — investigate"
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
# 6. Wait for health (use Host header so TrustedHost middleware accepts it)
# ------------------------------------------------------------------------------
say "Waiting for backend health on localhost:${BACKEND_HOST_PORT}..."
for i in $(seq 1 60); do
  if curl -fs -H "Host: api.${PROD_DOMAIN}" \
        "http://localhost:${BACKEND_HOST_PORT}/health" >/dev/null 2>&1; then
    ok "backend healthy"; break
  fi
  sleep 1
  if [ "$i" = 60 ]; then die "backend never became healthy — $DC logs backend"; fi
done

say "Waiting for frontend on localhost:${FRONTEND_HOST_PORT}..."
for i in $(seq 1 30); do
  if curl -fs -o /dev/null -w "%{http_code}" \
        "http://localhost:${FRONTEND_HOST_PORT}" \
        | grep -qE "^(200|301|302|307|308)$"; then
    ok "frontend responding"; break
  fi
  sleep 1
  if [ "$i" = 30 ]; then die "frontend never came up — $DC logs frontend"; fi
done

# ------------------------------------------------------------------------------
# 7. Schema convergence + migrations + seeder (additive, idempotent)
# ------------------------------------------------------------------------------
# Mirrors install_app.sh — handles the case where deploy.sh is somehow run on a
# DB that's missing the alembic_version table or the baseline schema. On a
# normal redeploy this is a no-op (alembic upgrade head finds nothing new).
HAS_USERS=$($DC exec -T postgres psql -U cpmai -d cpmai_prep -At \
              -c "SELECT to_regclass('public.users') IS NOT NULL" 2>/dev/null \
              | tail -1)
HAS_ALEMBIC=$($DC exec -T postgres psql -U cpmai -d cpmai_prep -At \
                -c "SELECT to_regclass('public.alembic_version') IS NOT NULL" 2>/dev/null \
                | tail -1)
if [ "$HAS_USERS" != "t" ]; then
  say "Fresh DB detected — bootstrapping schema before alembic..."
  $DC exec -T backend python -c "
import app.models  # noqa: F401
from app.core.database import Base, engine
Base.metadata.create_all(bind=engine)
print('schema created')
"
  $DC exec -T backend bash -c 'cd /app && alembic stamp head' >/dev/null
  ok "schema bootstrapped + stamped"
elif [ "$HAS_ALEMBIC" != "t" ]; then
  say "Existing schema, no alembic table — stamping baseline + upgrading..."
  $DC exec -T backend bash -c 'cd /app && alembic stamp 0003_payment_providers' >/dev/null
  $DC exec -T backend bash -c 'cd /app && alembic upgrade head'
  ok "stamped + upgraded"
else
  say "Running alembic upgrade head (additive only)..."
  $DC exec -T backend bash -c 'cd /app && alembic upgrade head'
  ok "schema at head"
fi

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
# 9. Smoke — runs against the public URL (validates DNS → Caddy → backend → DB)
# ------------------------------------------------------------------------------
say "Running smoke against $SMOKE_BASE_URL..."
BASE_URL="$SMOKE_BASE_URL" python3 scripts/smoke_admin_crud.py || {
  warn "smoke FAILED — site may be broken"
  warn "rollback with: ./scripts/vps/restore.sh /var/backups/cpmai-prep/<latest>.sql.gz"
  die "deploy aborted"
}

# ------------------------------------------------------------------------------
# 10. Reclaim disk — drop dangling images + builder cache older than the
#     rollback window. Each `compose build` overwrites :latest and orphans
#     the previous tag; left unchecked these accumulate at ~500MB/each
#     and eventually fill the VPS disk.
#
# Retention: 168h (7 days) — long enough to manually `docker tag` an
# older image back to :latest and `compose up -d` if a regression ships.
# `-a` removes any unused image (not just dangling), but currently-running
# containers' images are NEVER removed by `image prune`. Same for builder
# cache — only inactive cache mounts get reclaimed.
# ------------------------------------------------------------------------------
say "Reclaiming disk: pruning images + builder cache older than 7d..."
PRUNED_IMG=$(docker image prune -af --filter "until=168h" 2>&1 \
              | awk '/Total reclaimed/ {print $NF}' || echo "0B")
PRUNED_BLD=$(docker builder prune -af --filter "until=168h" 2>&1 \
              | awk '/Total reclaimed/ {print $NF}' || echo "0B")
ok "reclaimed: images=${PRUNED_IMG:-0B}  builder=${PRUNED_BLD:-0B}"

ELAPSED=$(( $(date +%s) - START_TS ))
echo
echo "${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
echo "${G}✓ Deploy complete${X}  ${START_SHA} → ${NEW_SHA}  in ${ELAPSED}s"
echo "${G}  data preserved · migrations applied · smoke green${X}"
echo "${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
