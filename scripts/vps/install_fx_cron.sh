#!/usr/bin/env bash
# ==============================================================================
# install_fx_cron.sh — idempotent FX-refresh cron-entry installer
# ==============================================================================
# Adds (or refreshes) the daily FX rate-refresh cron entry. Called by
# deploy.sh on every deploy, so the admin never has to SSH to install
# or update the entry.
#
# Schedule: every day at 04:23 UTC.
#
# Why 04:23 UTC:
#   ECB publishes Frankfurter reference rates ~16:00 CET (15:00 UTC
#   winter / 14:00 UTC summer). By 04:23 UTC the NEXT morning, the
#   data is ~13-14 hours fresh and stable. The :23 minute offset
#   avoids the herd of crons at :00.
#
# Why daily, not weekly/monthly:
#   FX rates can drift several % in a week. Daily refresh keeps quoted
#   prices reasonably close to live mid-market. The Frankfurter API
#   is free + no rate limit, so cost is zero.
#
# Idempotent — strips any existing fx_refresh.sh line before re-adding.
# ==============================================================================
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/../.."; pwd)}"
REFRESH_SCRIPT="$APP_DIR/scripts/vps/fx_refresh.sh"
CRON_LOG="/var/log/cpmai/fx_refresh_cron.log"
SCHEDULE="23 4 * * *"

say() { printf '==> %s\n' "$*"; }
ok()  { printf '  ✓ %s\n' "$*"; }
die() { printf '  ✗ %s\n' "$*" >&2; exit 1; }

[ -x "$REFRESH_SCRIPT" ] || die "$REFRESH_SCRIPT not found or not executable. \
chmod +x scripts/vps/fx_refresh.sh first."

CRON_LINE="$SCHEDULE APP_DIR=$APP_DIR $REFRESH_SCRIPT >> $CRON_LOG 2>&1"

say "Refreshing crontab entry for fx_refresh.sh"
(crontab -l 2>/dev/null | grep -v 'fx_refresh\.sh' ; echo "$CRON_LINE") \
  | crontab -

ok "cron entry installed:"
echo "    $CRON_LINE"

if ! crontab -l 2>/dev/null | grep -q 'fx_refresh\.sh'; then
  die "entry did not stick — check crontab manually"
fi
