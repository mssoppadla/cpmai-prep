#!/usr/bin/env bash
# ==============================================================================
# install_geoip.sh — one-time bootstrap for the GeoIP feature
# ==============================================================================
# Run once as the `deploy` user, AFTER:
#   • install_app.sh has completed (the app is running)
#   • An admin has set geoip.maxmind_account_id and geoip.maxmind_license_key
#     via /admin/settings → they're stored in the system_settings table
#
# What it does, idempotently:
#   1. Creates /srv/cpmai/geoip/ with the right owner + perms
#   2. Creates /var/log/cpmai/ for refresh logs
#   3. Runs an initial database refresh via the backend's CLI (which
#      reads credentials from the live system_settings table)
#   4. Calls install_geoip_cron.sh to wire up the recurring refresh
#      cron (Wed + Sat 04:17 UTC, aligned with MaxMind's Tue/Fri
#      release schedule)
#
# Running again is safe — every step is idempotent. Re-running is the
# correct response to "we rotated the license key and want to confirm
# everything still works."
#
# Usage:  ./scripts/vps/install_geoip.sh
# ==============================================================================
set -euo pipefail

cd "$(dirname "$0")/../.."
APP_DIR="$(pwd)"
GEOIP_DIR="/srv/cpmai/geoip"
LOG_DIR="/var/log/cpmai"

say()   { printf '==> %s\n' "$*"; }
ok()    { printf '  ✓ %s\n' "$*"; }
warn()  { printf '  ! %s\n' "$*" >&2; }
die()   { printf '  ✗ %s\n' "$*" >&2; exit 1; }

# Sanity check.
[ "$(id -u)" -ne 0 ] || die "Run as the deploy user, NOT root."
command -v docker >/dev/null || die "docker not on PATH."
docker compose version >/dev/null 2>&1 || die "docker compose plugin missing."

# ------------------------------------------------------------------------------
# 1. Filesystem layout
# ------------------------------------------------------------------------------
say "Ensuring directory layout"

# /srv/cpmai owned by deploy:deploy so the backend container's bind
# mount can read+write it. The geoip subdir is what the backend points
# at via the DEFAULT_DB_PATH constant.
if [ ! -d "$GEOIP_DIR" ]; then
  sudo mkdir -p "$GEOIP_DIR"
  ok "created $GEOIP_DIR"
else
  ok "$GEOIP_DIR already exists"
fi
sudo chown -R "$(id -un):$(id -gn)" "/srv/cpmai"
sudo chmod 755 "$GEOIP_DIR"

# Log dir for the cron-run refresh script.
if [ ! -d "$LOG_DIR" ]; then
  sudo mkdir -p "$LOG_DIR"
  sudo chown -R "$(id -un):$(id -gn)" "$LOG_DIR"
  ok "created $LOG_DIR"
fi

# ------------------------------------------------------------------------------
# 2. Mount the geoip dir into the backend container
# ------------------------------------------------------------------------------
# The docker-compose.production.yml exposes /srv/cpmai/geoip as a bind
# mount on the backend service (added in the deploy.sh changes). If
# the mount isn't present, the refresh would write to a container-local
# path that disappears on next deploy. We sanity-check by trying to
# touch a file from inside the container.
say "Verifying container can write to $GEOIP_DIR"
SENTINEL="$GEOIP_DIR/.install_geoip_sentinel"
echo "ok" > "$SENTINEL"
if docker compose -f docker-compose.production.yml exec -T backend \
     test -f "/srv/cpmai/geoip/.install_geoip_sentinel"; then
  ok "container sees $GEOIP_DIR"
else
  rm -f "$SENTINEL"
  die "backend container can NOT read $GEOIP_DIR — bind mount missing. "\
      "Check docker-compose.production.yml has - /srv/cpmai/geoip:/srv/cpmai/geoip "\
      "under the backend service."
fi
rm -f "$SENTINEL"

# ------------------------------------------------------------------------------
# 3. Initial database refresh
# ------------------------------------------------------------------------------
say "Running initial GeoLite2-City download (this reads MaxMind credentials "\
    "from the system_settings table — set them via /admin/settings first)"
if ! docker compose -f docker-compose.production.yml exec -T backend \
     python -m app.services.geoip refresh; then
  warn "Refresh failed. Common causes:"
  warn "  • Credentials not set yet: log in as admin → /admin/settings → "
  warn "    set geoip.maxmind_account_id + geoip.maxmind_license_key"
  warn "  • Network problem from VPS to download.maxmind.com"
  warn "  • License key rejected — verify at maxmind.com → My License Keys"
  warn ""
  warn "After fixing, re-run this script (idempotent)."
  exit 1
fi
ok "initial database installed"

# ------------------------------------------------------------------------------
# 4. Install cron
# ------------------------------------------------------------------------------
"$APP_DIR/scripts/vps/install_geoip_cron.sh"

say "Done. The cron will refresh the DB automatically (Wed + Sat 04:17 UTC,"
say "      aligned with MaxMind's Tuesday + Friday releases)."
say "Verify with:  curl https://api.<your-domain>/health | jq .geoip"
