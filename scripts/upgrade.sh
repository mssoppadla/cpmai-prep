#!/usr/bin/env bash
# ==============================================================================
# upgrade.sh — every-deploy entry point
# ==============================================================================
# Use this on every deploy after the first one (i.e., after bootstrap.sh has
# successfully run once on the target).
#
# What it does:
#   1. Snapshots row counts of guarded tables (users, payments, etc.)
#   2. Runs `alembic upgrade head` (additive migrations only — code review
#      should reject any migration that DROPs data).
#   3. Runs the idempotent seeder (top-up settings/topics if you added new
#      defaults; never modifies existing rows).
#   4. Restarts the backend container if running in docker.
#   5. Verifies that no guarded table's row count decreased.
#   6. Runs the smoke test against the upgraded service.
#
# Exits non-zero if any check fails — including the data-preservation check.
# Safe to run on every deploy; prevents accidental data loss.
#
# Usage:
#     ./scripts/upgrade.sh
#
# Override the docker-compose project name or services if you run a custom
# topology by setting COMPOSE_FILE / COMPOSE_PROJECT_NAME normally.
# ==============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."
B=$'\033[1m'; G=$'\033[0;32m'; Y=$'\033[0;33m'; C=$'\033[0;36m'; X=$'\033[0m'
say()  { echo "${C}→${X} $*"; }
ok()   { echo "${G}✓${X} $*"; }
die()  { echo "✗ $*" >&2; exit 1; }

PY="$(command -v python3 || command -v python)" \
    || die "python not on PATH"

# ------------------------------------------------------------------------------
# 1. Snapshot before
# ------------------------------------------------------------------------------
say "Pre-deploy data snapshot..."
"$PY" scripts/preserve_users_check.py snapshot

# ------------------------------------------------------------------------------
# 2. Migrations (additive only)
# ------------------------------------------------------------------------------
say "Running alembic upgrade head..."
docker compose exec -T backend bash -c 'cd /app && alembic upgrade head'
ok "schema at head"

# ------------------------------------------------------------------------------
# 3. Seeder (idempotent)
# ------------------------------------------------------------------------------
say "Running idempotent seeder..."
docker compose exec -T backend python seeds/seed.py
ok "seeder done"

# ------------------------------------------------------------------------------
# 4. Restart backend (picks up new code in case env or image changed)
# ------------------------------------------------------------------------------
say "Restarting backend..."
docker compose up -d --force-recreate backend
for i in $(seq 1 60); do
  if curl -fs http://localhost:8000/health >/dev/null 2>&1; then
    ok "backend healthy after restart"
    break
  fi
  sleep 1
  if [ "$i" = 60 ]; then die "backend did not come back up — check logs"; fi
done

# ------------------------------------------------------------------------------
# 5. Data-preservation check
# ------------------------------------------------------------------------------
say "Verifying no guarded table lost rows..."
"$PY" scripts/preserve_users_check.py verify

# ------------------------------------------------------------------------------
# 6. Smoke test
# ------------------------------------------------------------------------------
say "Running smoke test..."
"$PY" scripts/smoke_admin_crud.py

echo
echo "${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
echo "${G}✓ Upgrade complete — data preserved, smoke green${X}"
echo "${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
