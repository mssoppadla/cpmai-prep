#!/usr/bin/env bash
# ==============================================================================
# bootstrap.sh — first-time setup, idempotent, safe to re-run
# ==============================================================================
# Brings a brand-new clone (or a stale one) to a runnable state:
#
#   1. Generates backend/.env and frontend/.env.local from .env.example if
#      they don't already exist (with fresh SECRET_KEY / ENCRYPTION_KEY).
#      EXISTING ENV FILES ARE NEVER OVERWRITTEN.
#   2. Starts the docker stack (postgres, redis, backend) — frontend is
#      run separately via `npm run dev` so HMR works on the host.
#   3. Creates DB schema for fresh DBs (Base.metadata.create_all) and
#      stamps the new DB at the alembic head, OR runs `alembic upgrade head`
#      on existing DBs (additive only — never drops data).
#   4. Runs the idempotent seeder (settings, topics, super-admin, sample
#      questions/sets only on empty tables).
#   5. Runs scripts/smoke_admin_crud.py end-to-end.
#
# Existing user data is preserved on every step. Run this in any
# environment (local laptop, fresh VPS, CI runner) to converge to a
# known-good state.
# ==============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."
B=$'\033[1m'; G=$'\033[0;32m'; Y=$'\033[0;33m'; C=$'\033[0;36m'; X=$'\033[0m'
say()  { echo "${C}→${X} $*"; }
ok()   { echo "${G}✓${X} $*"; }
warn() { echo "${Y}!${X} $*"; }
die()  { echo "✗ $*" >&2; exit 1; }

command -v docker  >/dev/null || die "docker not on PATH"
command -v python3 >/dev/null 2>&1 || command -v python >/dev/null \
                                          || die "python not on PATH"
PY="$(command -v python3 || command -v python)"

# ------------------------------------------------------------------------------
# 1. Env files — generate only if missing
# ------------------------------------------------------------------------------
say "Checking env files..."
if [ ! -f backend/.env ]; then
  say "Creating backend/.env from template..."
  cp backend/.env.example backend/.env
  SECRET=$("$PY" -c 'import secrets; print(secrets.token_urlsafe(48))')
  FERNET=$("$PY" -c 'import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())')
  ADMIN_PW=$("$PY" -c 'import secrets; print(secrets.token_urlsafe(18))')
  # POSIX-portable in-place edit
  TMP=$(mktemp)
  awk -v s="$SECRET" -v f="$FERNET" -v p="$ADMIN_PW" '
    /^SECRET_KEY=/        { print "SECRET_KEY=" s;       next }
    /^ENCRYPTION_KEY=/    { print "ENCRYPTION_KEY=" f;   next }
    /^BOOTSTRAP_ADMIN_PASSWORD=/ { print "BOOTSTRAP_ADMIN_PASSWORD=" p; next }
    /^ALLOWED_HOSTS=/     { print "ALLOWED_HOSTS=[\"localhost\",\"127.0.0.1\"]"; next }
    /^CORS_ORIGINS=/      { print "CORS_ORIGINS=[\"http://localhost:3000\"]"; next }
    { print }
  ' backend/.env > "$TMP" && mv "$TMP" backend/.env
  ok "backend/.env created with fresh secrets"
  warn "Generated admin password — find it in backend/.env (BOOTSTRAP_ADMIN_PASSWORD)"
else
  ok "backend/.env already present (left untouched)"
fi

if [ ! -f frontend/.env.local ]; then
  cp frontend/.env.example frontend/.env.local
  ok "frontend/.env.local created from template"
else
  ok "frontend/.env.local already present (left untouched)"
fi

# ------------------------------------------------------------------------------
# 2. Docker services
# ------------------------------------------------------------------------------
say "Starting docker stack (postgres, redis, backend)..."
docker compose up -d postgres redis backend

# Wait for backend health
say "Waiting for backend /health..."
for i in $(seq 1 60); do
  if curl -fs http://localhost:8000/health >/dev/null 2>&1; then
    ok "backend healthy"
    break
  fi
  sleep 1
  if [ "$i" = 60 ]; then die "backend never became healthy — check 'docker compose logs backend'"; fi
done

# ------------------------------------------------------------------------------
# 3. Schema convergence — alembic for existing DBs, create_all for fresh
# ------------------------------------------------------------------------------
say "Converging DB schema..."
HAS_ALEMBIC_TBL=$(docker compose exec -T postgres psql -U cpmai -d cpmai_prep -At \
  -c "SELECT to_regclass('public.alembic_version') IS NOT NULL" 2>/dev/null \
  | tail -1)
HAS_USERS_TBL=$(docker compose exec -T postgres psql -U cpmai -d cpmai_prep -At \
  -c "SELECT to_regclass('public.users') IS NOT NULL" 2>/dev/null \
  | tail -1)

if [ "$HAS_USERS_TBL" != "t" ]; then
  say "Fresh DB — creating schema from SQLAlchemy models, then stamping alembic to head..."
  docker compose exec -T backend python -c "
import app.models  # noqa
from app.core.database import Base, engine
Base.metadata.create_all(bind=engine)
print('schema created')
"
  docker compose exec -T backend bash -c 'cd /app && alembic stamp head' >/dev/null
  ok "fresh schema created + stamped"
elif [ "$HAS_ALEMBIC_TBL" != "t" ]; then
  say "Existing schema, no alembic table — stamping baseline then upgrading..."
  docker compose exec -T backend bash -c 'cd /app && alembic stamp 0003_payment_providers' >/dev/null
  docker compose exec -T backend bash -c 'cd /app && alembic upgrade head'
  ok "stamped + upgraded to head"
else
  say "Running alembic upgrade head (additive only)..."
  docker compose exec -T backend bash -c 'cd /app && alembic upgrade head'
  ok "schema is at head"
fi

# ------------------------------------------------------------------------------
# 4. Seeder (idempotent — never overwrites)
# ------------------------------------------------------------------------------
say "Running seeder..."
docker compose exec -T backend python seeds/seed.py
ok "seeder done (idempotent)"

# ------------------------------------------------------------------------------
# 5. Smoke test
# ------------------------------------------------------------------------------
say "Running smoke test..."
"$PY" scripts/smoke_admin_crud.py
ok "smoke test green"

# ------------------------------------------------------------------------------
# Done
# ------------------------------------------------------------------------------
echo
echo "${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
echo "${G}✓ Bootstrap complete${X}"
echo "${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
echo
echo "${B}What's running:${X}"
echo "  • postgres:  localhost:5433 (db=cpmai_prep, user=cpmai)"
echo "  • redis:     localhost:6379"
echo "  • backend:   http://localhost:8000   (docs: /docs)"
echo
echo "${B}Next steps:${X}"
echo "  • cd frontend && npm install && npm run dev   # http://localhost:3000"
echo "  • Admin sign-in:  see BOOTSTRAP_ADMIN_EMAIL/PASSWORD in backend/.env"
echo "  • Tail logs:      tail -f backend/logs/app.jsonl"
echo
echo "${B}For Google sign-in:${X}"
echo "  • See docs/google-auth-setup.md (one-time Cloud Console steps)"
echo "  • Set GOOGLE_OAUTH_CLIENT_ID in backend/.env and"
echo "        NEXT_PUBLIC_GOOGLE_CLIENT_ID in frontend/.env.local"
echo "  • Restart with: ./scripts/upgrade.sh"
