#!/usr/bin/env bash
# ==============================================================================
# install_geoip_cron.sh — idempotent cron-entry installer
# ==============================================================================
# Adds (or refreshes) the cron entry that runs scripts/vps/geoip_refresh.sh
# every minute. The schedule that the refresh actually USES lives in
# the system_settings table (key: geoip.refresh_schedule) and is editable
# from the admin UI without redeploy.
#
# Why every-minute, not the actual refresh cadence:
#   We want the admin to be able to change the refresh schedule from
#   /admin/geoip — no SSH, no crontab edit. Cron itself reads from
#   /etc/crontab and can't pull from our DB. So we keep the cron line
#   STATIC at every-minute and put the actual decision logic inside
#   the Python CLI: ``refresh --only-if-scheduled`` checks the
#   geoip.refresh_schedule setting and exits silently when the current
#   minute doesn't match.
#
#   The result: schedule changes take effect on the very next minute.
#   No SSH, no crontab edit, no service restart.
#
# Default schedule (geoip.refresh_schedule):
#   "17 4 * * 3,6" — Wednesdays and Saturdays at 04:17 UTC, aligned
#   with MaxMind's Tuesday + Friday release cadence (releases happen
#   ~14:00–22:00 UTC, we pick them up the next morning).
#   Edit at /admin/geoip → Schedule card → save. The schedule field
#   has a "next 3 runs" preview so you can sanity-check before saving.
#
# Cost of every-minute cron:
#   1,440 invocations per day. ~1,438 of them exit immediately when the
#   schedule's not matched (one settings read + one cron-expression
#   match — total ~50ms). Only the 2-or-so per week that match actually
#   do work. Net CPU on the VPS: ~30 min/day, negligible.
#
# Refresh kill switch:
#   The geoip.refresh_enabled setting is a separate, independent gate.
#   With refresh_enabled=false, even a matched schedule won't refresh —
#   useful during a known MaxMind outage. Re-enable in /admin/settings.
#
# Idempotency: we strip any existing line containing "geoip_refresh.sh"
# from the current crontab before adding the canonical line. Re-running
# is the right way to refresh the entry if the path or container name
# changes.
#
# Usage:  ./scripts/vps/install_geoip_cron.sh
# ==============================================================================
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/../.."; pwd)}"
REFRESH_SCRIPT="$APP_DIR/scripts/vps/geoip_refresh.sh"
CRON_LOG="/var/log/cpmai/geoip_refresh_cron.log"
# Cron format: minute hour day-of-month month day-of-week.
# "* * * * *" = every minute. The script gates the actual refresh
# against geoip.refresh_schedule (admin-editable in /admin/geoip).
SCHEDULE="* * * * *"

say() { printf '==> %s\n' "$*"; }
ok()  { printf '  ✓ %s\n' "$*"; }
die() { printf '  ✗ %s\n' "$*" >&2; exit 1; }

[ -x "$REFRESH_SCRIPT" ] || die "$REFRESH_SCRIPT not found or not executable. \
chmod +x scripts/vps/geoip_refresh.sh first."

# ------------------------------------------------------------------------------
# Build the canonical cron line.
# Setting APP_DIR= so the refresh script works even when cron starts
# with a minimal env (no CWD inheritance).
# ------------------------------------------------------------------------------
CRON_LINE="$SCHEDULE APP_DIR=$APP_DIR $REFRESH_SCRIPT >> $CRON_LOG 2>&1"

# ------------------------------------------------------------------------------
# Replace any previous entry. We match on the script basename rather
# than the full line so a path change still cleans up.
# ------------------------------------------------------------------------------
say "Refreshing crontab entry for geoip_refresh.sh"
(crontab -l 2>/dev/null | grep -v 'geoip_refresh\.sh' ; echo "$CRON_LINE") \
  | crontab -

ok "cron entry installed:"
echo "    $CRON_LINE"

# Verify the line is now present.
if ! crontab -l 2>/dev/null | grep -q 'geoip_refresh\.sh'; then
  die "entry did not stick — check crontab manually"
fi
