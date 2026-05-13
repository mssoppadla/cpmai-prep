#!/usr/bin/env bash
# ==============================================================================
# fx_refresh.sh — daily FX-rate refresh from Frankfurter (ECB)
# ==============================================================================
# Cron-invoked daily at 04:23 UTC, OR manually for troubleshooting. The
# actual fetch + sanity-cap + persist logic lives in the Python CLI
# (``python -m app.services.fx refresh``) — this shell wrapper adds:
#
#   • flock guard:    prevents concurrent runs
#   • timeout:        60s — Frankfurter rarely takes >2s, but we cap
#                     so a stuck request can't pile up
#   • logging:        tees output to /var/log/cpmai/fx_refresh.log
#   • exit code:      forwards the CLI exit code so cron alerts have
#                     the right signal
#
# Exit codes (from the CLI):
#   0 = success
#   1 = network (Frankfurter unreachable / non-200)
#   2 = data    (Frankfurter response malformed)
#   3 = sanity  (cap rejected >50% of rates — bad upstream payload)
#   4 = misuse  (cron should never hit this)
#  >=130 = killed by timeout
#
# Why a separate cron from geoip_refresh.sh:
#   GeoIP and FX refresh on different cadences (GeoIP twice weekly to
#   match MaxMind, FX daily to match ECB). Sharing a cron line would
#   tie them together unnecessarily. Each script does one thing.
#
# Usage:  ./scripts/vps/fx_refresh.sh
#
# Cron:   23 4 * * * /opt/cpmai-prep/scripts/vps/fx_refresh.sh \
#                       >> /var/log/cpmai/fx_refresh_cron.log 2>&1
# (Every day at 04:23 UTC. ECB publishes ~16:00 CET; by 04:23 UTC the
#  next morning, the new rates are ~12 hours old at the source.)
# ==============================================================================
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/cpmai-prep}"
LOG_FILE="${FX_REFRESH_LOG:-/var/log/cpmai/fx_refresh.log}"
LOCK_FILE="${FX_REFRESH_LOCK:-/var/lock/cpmai-fx-refresh.lock}"
TIMEOUT_SECONDS="${FX_REFRESH_TIMEOUT:-60}"

LOG_DIR="$(dirname "$LOG_FILE")"
[ -d "$LOG_DIR" ] || mkdir -p "$LOG_DIR" 2>/dev/null || true

ts()  { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
log() { printf '[%s] %s\n' "$(ts)" "$*" | tee -a "$LOG_FILE"; }

# ------------------------------------------------------------------------------
# flock guard
# ------------------------------------------------------------------------------
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "another fx_refresh is already running — exiting cleanly."
  exit 0
fi
log "fx_refresh starting (pid=$$)"

# ------------------------------------------------------------------------------
# Hard timeout watchdog
# ------------------------------------------------------------------------------
(
  sleep "$TIMEOUT_SECONDS"
  if kill -0 $$ 2>/dev/null; then
    log "TIMEOUT after ${TIMEOUT_SECONDS}s — killing pid=$$"
    kill -TERM $$ 2>/dev/null || true
  fi
) &
TIMEOUT_PID=$!

cleanup() { kill "$TIMEOUT_PID" 2>/dev/null || true; }
trap cleanup EXIT

cd "$APP_DIR"

# ------------------------------------------------------------------------------
# Invoke the Python CLI. Always log output (unlike geoip_refresh which
# silences non-scheduled minutes — FX is daily, so every run produces
# meaningful output and we want it all in the log).
# ------------------------------------------------------------------------------
log "invoking python -m app.services.fx refresh"
set +e
docker compose -f docker-compose.production.yml exec -T backend \
    python -m app.services.fx refresh 2>&1 | tee -a "$LOG_FILE"
RC=${PIPESTATUS[0]}
set -e

case "$RC" in
  0) log "refresh completed successfully (exit 0)" ;;
  1) log "NETWORK error (exit 1) — check Frankfurter / VPS connectivity" ;;
  2) log "DATA error (exit 2) — Frankfurter response malformed; file a bug" ;;
  3) log "SANITY cap rejected the fetch (exit 3) — investigate before retry" ;;
  *) log "unexpected exit code $RC" ;;
esac

log "fx_refresh exiting with code $RC"
exit "$RC"
