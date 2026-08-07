#!/usr/bin/env bash
# ==============================================================================
# rehearse_deploy.sh — run deploy.sh's DB-critical sequence locally
# ==============================================================================
# Why this exists: passing pytest is NOT enough. On 2026-08-07 a migration
# that DELETEd rows from `exam_sessions` sailed through the test suite and a
# manual `alembic upgrade`, then aborted the production deploy and triggered
# an auto-rollback — because deploy.sh runs a data-preservation guard that
# refuses to finish when a GUARDED_TABLE loses rows. Nothing local exercised
# that guard.
#
# This script mimics the prod order against your LOCAL dev database:
#
#   snapshot guarded row counts  →  alembic upgrade head  →  guard verify
#   →  alembic downgrade (one step)  →  alembic upgrade head  (rollback-safe)
#
# Run it before pushing ANY migration, compose, or deploy-script change.
#
# Usage (from repo root, with the compose postgres running):
#     ./scripts/rehearse_deploy.sh
#
# Env:
#   DATABASE_URL  — defaults to the local dev DB on port 5433
#   PY            — python interpreter (defaults to the 3.12 venv)
# ==============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."

G=$'\033[0;32m'; R=$'\033[0;31m'; C=$'\033[0;36m'; X=$'\033[0m'
say() { echo "${C}==>${X} $*"; }
ok()  { echo "${G}  ✓${X} $*"; }
die() { echo "${R}  ✗ $*${X}" >&2; exit 1; }

PY="${PY:-backend/.venv312/Scripts/python.exe}"
[ -x "$PY" ] || PY="${PY:-python3}"

: "${DATABASE_URL:=postgresql+psycopg2://cpmai:cpmai@localhost:5433/cpmai_prep}"
export DATABASE_URL

# The guard script talks to the DB through a command it shells out to; point
# it at the local compose container.
export PRESERVE_DB_CMD="${PRESERVE_DB_CMD:-docker exec -i cpmai-prep-postgres-1 psql -U cpmai -d cpmai_prep -At -c}"
export PRESERVE_SNAPSHOT_PATH="${PRESERVE_SNAPSHOT_PATH:-/tmp/cpmai-rehearse-snapshot.json}"

say "1/5 Snapshotting guarded row counts (deploy.sh step 3)"
"$PY" scripts/preserve_users_check.py snapshot || die "snapshot failed"
ok "snapshot written to $PRESERVE_SNAPSHOT_PATH"

say "2/5 alembic upgrade head (deploy.sh step 5)"
(cd backend && "../$PY" -m alembic upgrade head) || die "migration failed"
ok "migrations applied"

say "3/5 Data-preservation verify (deploy.sh step 8 — THE one that bit us)"
"$PY" scripts/preserve_users_check.py verify \
  || die "GUARD FAILED — this change would abort the prod deploy and roll back.
     Fix: never DELETE from a guarded table in a migration or a hot code
     path; mark rows with a status the read paths filter out instead."
ok "no guarded table lost rows"

say "4/5 Rollback rehearsal: downgrade one revision, then upgrade again"
PREV="$(cd backend && "../$PY" -m alembic heads 2>/dev/null | head -1 | awk '{print $1}')"
(cd backend && "../$PY" -m alembic downgrade -1) || die "downgrade failed"
ok "downgrade clean"
(cd backend && "../$PY" -m alembic upgrade head) || die "re-upgrade failed"
ok "re-upgrade clean (migration is replayable)"

say "5/5 Guard verify once more (post-rollback-cycle)"
"$PY" scripts/preserve_users_check.py verify || die "guard failed after replay"

echo
echo "${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
echo "${G}✓ Deploy rehearsal passed${X} — head=${PREV:-unknown}"
echo "${G}  guard green · migration replayable · safe to push${X}"
echo "${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
