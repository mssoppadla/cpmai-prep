#!/usr/bin/env bash
# ==============================================================================
# install_app.sh — first-time app install on a provisioned VPS
# ==============================================================================
# Run once as the `deploy` user, AFTER:
#   • provision.sh has run (Docker + Caddy + firewall installed)
#   • the repo has been cloned to /opt/cpmai-prep
#   • DNS A records for the production domain point at this VPS
#
# What it does, idempotently:
#   1. Generates backend/.env from .env.example with fresh secrets if absent
#      (prompts for the values only YOU know: domain, Google client ID,
#      Razorpay keys, admin email)
#   2. Generates frontend/.env.local with the matching public values
#   3. Installs the production Caddyfile at /etc/caddy/Caddyfile (with
#      a backup of any existing one)
#   4. Builds + starts the production docker stack
#   5. Runs migrations + seeder (idempotent — never overwrites data)
#   6. Installs daily backup cron (at 02:30 server time)
#   7. Runs the smoke test against the live stack
#
# RUNNING TWICE IS SAFE — it never overwrites existing env files or data.
#
# Usage:   ./scripts/vps/install_app.sh
# ==============================================================================
set -euo pipefail

cd "$(dirname "$0")/../.."
APP_DIR="$(pwd)"
say()   { printf '==> %s\n' "$*"; }
ok()    { printf '  ✓ %s\n' "$*"; }
warn()  { printf '  ! %s\n' "$*" >&2; }
die()   { printf '  ✗ %s\n' "$*" >&2; exit 1; }
prompt() { local v; read -rp "$1: " v; echo "$v"; }

[ "$(id -u)" -ne 0 ] || die "Run as the deploy user, NOT root."
command -v docker  >/dev/null || die "docker not on PATH — run provision.sh first."
docker compose version >/dev/null 2>&1 || die "docker compose plugin missing."

# ------------------------------------------------------------------------------
# 1. backend/.env
# ------------------------------------------------------------------------------
if [ ! -f backend/.env ]; then
  say "Generating backend/.env (one-time)"
  cp backend/.env.example backend/.env

  PROD_DOMAIN=$(prompt "Production domain (e.g. cpmaiexamprep.com)")
  GOOGLE_CID=$(prompt "Google OAuth Client ID (or blank to disable Google sign-in)")
  RP_KEY_ID=$(prompt "Razorpay Key ID (rzp_test_… or rzp_live_…, blank to skip)")
  RP_SECRET=""
  RP_WEBHOOK=""
  if [ -n "$RP_KEY_ID" ]; then
    RP_SECRET=$(prompt "Razorpay Key SECRET")
    RP_WEBHOOK=$(prompt "Razorpay webhook signing secret")
  fi
  ADMIN_EMAIL=$(prompt "Bootstrap admin email (e.g. admin@${PROD_DOMAIN})")

  # Persist deploy-time config in a sidecar file so re-runs (and deploy.sh)
  # can read it back without trying to parse JSON out of ALLOWED_HOSTS.
  #
  # BACKEND_HOST_PORT / FRONTEND_HOST_PORT default to 8000/3000 (the standard
  # docker-compose ports). Override here if your VPS reserves those ports
  # (e.g. Hostinger images sometimes block 8000). Caddy proxies to whatever
  # host port you set, so users see no difference.
  cat > .deploy.conf <<EOF
PROD_DOMAIN=${PROD_DOMAIN}
BACKEND_HOST_PORT=8000
FRONTEND_HOST_PORT=3000
EOF
  chmod 0600 .deploy.conf

  SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
  FERNET=$(python3 -c 'import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())')
  ADMIN_PW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
  # Smoke-test super-admin — separate from the operator account so that
  # rotating BOOTSTRAP_ADMIN_PASSWORD via /admin/users never breaks the
  # smoke. seed.py keeps the DB hash in sync with this value.
  SMOKE_PW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
  SMOKE_EMAIL="smoke-admin@${PROD_DOMAIN}"

  TMP=$(mktemp)
  awk -v s="$SECRET" -v f="$FERNET" -v p="$ADMIN_PW" \
      -v d="$PROD_DOMAIN" -v g="$GOOGLE_CID" \
      -v rk="$RP_KEY_ID" -v rs="$RP_SECRET" -v rw="$RP_WEBHOOK" \
      -v ae="$ADMIN_EMAIL" -v se="$SMOKE_EMAIL" -v sp="$SMOKE_PW" '
    /^APP_ENV=/                    { print "APP_ENV=production"; next }
    /^SECRET_KEY=/                 { print "SECRET_KEY=" s; next }
    /^ENCRYPTION_KEY=/             { print "ENCRYPTION_KEY=" f; next }
    /^BOOTSTRAP_ADMIN_EMAIL=/      { print "BOOTSTRAP_ADMIN_EMAIL=" ae; next }
    /^BOOTSTRAP_ADMIN_PASSWORD=/   { print "BOOTSTRAP_ADMIN_PASSWORD=" p; next }
    /^SMOKE_ADMIN_EMAIL=/          { print "SMOKE_ADMIN_EMAIL=" se; next }
    /^SMOKE_ADMIN_PASSWORD=/       { print "SMOKE_ADMIN_PASSWORD=" sp; next }
    /^ALLOWED_HOSTS=/              { print "ALLOWED_HOSTS=[\"" d "\",\"www." d "\",\"api." d "\"]"; next }
    /^CORS_ORIGINS=/               { print "CORS_ORIGINS=[\"https://" d "\",\"https://www." d "\"]"; next }
    /^GOOGLE_OAUTH_CLIENT_ID=/     { print "GOOGLE_OAUTH_CLIENT_ID=" g; next }
    /^RAZORPAY_KEY_ID=/            { print "RAZORPAY_KEY_ID=" rk; next }
    /^RAZORPAY_KEY_SECRET=/        { print "RAZORPAY_KEY_SECRET=" rs; next }
    /^RAZORPAY_WEBHOOK_SECRET=/    { print "RAZORPAY_WEBHOOK_SECRET=" rw; next }
    { print }
  ' backend/.env > "$TMP" && mv "$TMP" backend/.env
  chmod 0600 backend/.env

  ok "backend/.env created (mode 600)"
  warn "Bootstrap admin password (write down NOW, also stored in backend/.env):"
  warn "  email   : ${ADMIN_EMAIL}"
  warn "  password: ${ADMIN_PW}"
else
  ok "backend/.env already present (left untouched)"
fi

# Source backend/.env so we have GOOGLE_OAUTH_CLIENT_ID / RAZORPAY_KEY_ID
# for the frontend env file. ALLOWED_HOSTS is JSON-shaped and bash strips
# the quotes when sourcing — that's why we use .deploy.conf for PROD_DOMAIN.
set -a; . ./backend/.env; set +a

# Load PROD_DOMAIN + host port overrides — written above on first install,
# persisted across re-runs. docker-compose.prod.yml interpolates the *_PORT
# values for its loopback bindings.
[ -f .deploy.conf ] && { set -a; . ./.deploy.conf; set +a; }
[ -n "${PROD_DOMAIN:-}" ] || die ".deploy.conf missing PROD_DOMAIN — re-run from a fresh state"
: "${BACKEND_HOST_PORT:=8000}"
: "${FRONTEND_HOST_PORT:=3000}"
export BACKEND_HOST_PORT FRONTEND_HOST_PORT

# ------------------------------------------------------------------------------
# 2. frontend/.env.local
# ------------------------------------------------------------------------------
if [ ! -f frontend/.env.local ]; then
  say "Generating frontend/.env.local"
  cat > frontend/.env.local <<EOF
NEXT_PUBLIC_API_URL=https://api.${PROD_DOMAIN}/api/v1
NEXT_PUBLIC_GOOGLE_CLIENT_ID=${GOOGLE_OAUTH_CLIENT_ID:-}
NEXT_PUBLIC_RAZORPAY_KEY_ID=${RAZORPAY_KEY_ID:-}
NEXTAUTH_URL=https://${PROD_DOMAIN}
NEXTAUTH_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
EOF
  chmod 0600 frontend/.env.local
  ok "frontend/.env.local created"
else
  ok "frontend/.env.local already present (left untouched)"
fi

# ------------------------------------------------------------------------------
# 3. Caddyfile
# ------------------------------------------------------------------------------
if [ ! -f /etc/caddy/Caddyfile.cpmai-installed ]; then
  say "Installing production Caddyfile to /etc/caddy/Caddyfile"
  if [ -f /etc/caddy/Caddyfile ]; then
    sudo cp /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.bak.$(date +%s)"
  fi
  # Substitute hostname AND upstream ports so the Caddyfile reverse-proxies
  # to whatever ports the docker stack is using on this VPS.
  sudo sed -e "s/cpmaiexamprep\.com/${PROD_DOMAIN}/g" \
           -e "s/reverse_proxy localhost:3000/reverse_proxy localhost:${FRONTEND_HOST_PORT}/g" \
           -e "s/reverse_proxy localhost:8000/reverse_proxy localhost:${BACKEND_HOST_PORT}/g" \
           infra/Caddyfile \
    | sudo tee /etc/caddy/Caddyfile >/dev/null
  sudo touch /etc/caddy/Caddyfile.cpmai-installed
  sudo systemctl reload caddy
  ok "caddy reloaded — TLS will issue automatically on first request"
else
  ok "/etc/caddy/Caddyfile already installed (left untouched)"
fi

# ------------------------------------------------------------------------------
# 4. Build + start the production stack
# ------------------------------------------------------------------------------
# Pre-create the bind-mounted logs directory with the in-container app user's
# uid (999, from the backend Dockerfile's `useradd -r -g app app`). Without
# this, Docker auto-creates the dir as root:root and the container can't
# write to it.
mkdir -p backend/logs
sudo chown 999:999 backend/logs
sudo chmod 0755 backend/logs

say "Building + starting production stack"
# Source frontend/.env.local so NEXT_PUBLIC_* / NEXTAUTH_* are in the shell
# environment when `compose build` interpolates ${VAR} build args.
set -a; . ./frontend/.env.local; set +a
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
ok "containers up"

# Wait for backend health on the configured host port. Use the api.* hostname
# in the Host header so FastAPI's TrustedHost middleware accepts the request.
for i in $(seq 1 60); do
  if curl -fs -H "Host: api.${PROD_DOMAIN}" \
        "http://localhost:${BACKEND_HOST_PORT}/health" >/dev/null 2>&1; then
    ok "backend healthy"; break
  fi
  sleep 1
  if [ "$i" = 60 ]; then die "backend never became healthy — docker compose logs backend"; fi
done

# ------------------------------------------------------------------------------
# 5. Schema convergence + migrations + seeds
# ------------------------------------------------------------------------------
# 0001_baseline is intentionally a no-op (it stamps an existing schema).
# So on a fresh DB, bootstrap the schema via Base.metadata.create_all() before
# running alembic. Mirrors scripts/bootstrap.sh's "Schema convergence" block.
DC="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

HAS_USERS=$($DC exec -T postgres psql -U cpmai -d cpmai_prep -At \
              -c "SELECT to_regclass('public.users') IS NOT NULL" 2>/dev/null \
              | tail -1)
HAS_ALEMBIC=$($DC exec -T postgres psql -U cpmai -d cpmai_prep -At \
                -c "SELECT to_regclass('public.alembic_version') IS NOT NULL" 2>/dev/null \
                | tail -1)

if [ "$HAS_USERS" != "t" ]; then
  say "Fresh DB — creating schema from SQLAlchemy models, then stamping alembic..."
  $DC exec -T backend python -c "
import app.models  # noqa: F401  (imports register all models on Base)
from app.core.database import Base, engine
Base.metadata.create_all(bind=engine)
print('schema created')
"
  $DC exec -T backend bash -c 'cd /app && alembic stamp head' >/dev/null
  ok "fresh schema created + stamped to head"
elif [ "$HAS_ALEMBIC" != "t" ]; then
  say "Schema present but no alembic table — stamping baseline then upgrading..."
  $DC exec -T backend bash -c 'cd /app && alembic stamp 0003_payment_providers' >/dev/null
  $DC exec -T backend bash -c 'cd /app && alembic upgrade head'
  ok "stamped + upgraded to head"
else
  say "Running alembic upgrade head (additive only)..."
  $DC exec -T backend bash -c 'cd /app && alembic upgrade head'
  ok "schema is at head"
fi

say "Running idempotent seeder..."
$DC exec -T backend python seeds/seed.py
ok "seeds applied"

# ------------------------------------------------------------------------------
# 6. Backup cron — non-fatal
# ------------------------------------------------------------------------------
# Wrapped so a transient failure here doesn't abort the whole install with
# `set -e`. Worst case the operator runs `./scripts/vps/backup.sh` manually
# from cron later — the install itself is still good.
{
  CRON_LINE="30 2 * * * cd ${APP_DIR} && ./scripts/vps/backup.sh >> /var/log/cpmai-prep-backup.log 2>&1"
  if ! crontab -l 2>/dev/null | grep -F "${APP_DIR}/scripts/vps/backup.sh" >/dev/null; then
    say "Installing daily backup cron (02:30 server time)"
    ( crontab -l 2>/dev/null; echo "${CRON_LINE}" ) | crontab -
    sudo touch /var/log/cpmai-prep-backup.log
    sudo chown "$(whoami)" /var/log/cpmai-prep-backup.log
    ok "cron installed"
  else
    ok "backup cron already installed"
  fi
} || warn "cron install hit an issue — re-run manually or add via crontab -e"

# ------------------------------------------------------------------------------
# 7. Smoke — runs against the public URL so it validates the full chain
#    (DNS → Caddy TLS → backend → DB), not just localhost.
# ------------------------------------------------------------------------------
say "Running smoke against https://api.${PROD_DOMAIN}/api/v1"
BASE_URL="https://api.${PROD_DOMAIN}/api/v1" \
  python3 scripts/smoke_admin_crud.py \
    || die "smoke failed — investigate before going live"

echo
echo "============================================================"
echo "  ✓ Install complete"
echo "============================================================"
echo
echo "Public URLs (TLS issues automatically on first hit):"
PROD_DOMAIN_VALUE=$(echo "$ALLOWED_HOSTS" | sed -nE 's/.*"([^"]+)".*/\1/p' | head -1)
echo "  https://${PROD_DOMAIN_VALUE}/"
echo "  https://${PROD_DOMAIN_VALUE}/login"
echo "  https://${PROD_DOMAIN_VALUE}/admin"
echo "  https://api.${PROD_DOMAIN_VALUE}/health"
echo
echo "Sign in as super-admin: ${BOOTSTRAP_ADMIN_EMAIL}"
echo "  password is in backend/.env (BOOTSTRAP_ADMIN_PASSWORD)"
echo
echo "Future deploys: ./scripts/vps/deploy.sh"
echo "Manual backup : ./scripts/vps/backup.sh"
echo "Restore       : ./scripts/vps/restore.sh /var/backups/cpmai-prep/<file>.sql.gz"
