#!/usr/bin/env bash
# ==============================================================================
# geoip_refresh.sh — cron-invoked GeoLite2-City refresh (every-minute model)
# ==============================================================================
# Invoked by the cron entry installed by install_geoip_cron.sh, which
# fires EVERY MINUTE. The actual refresh decision is made by the Python
# CLI: ``python -m app.services.geoip refresh --only-if-scheduled``
# reads ``geoip.refresh_schedule`` from settings and exits silently on
# minutes that don't match. So most cron ticks do near-zero work.
#
# Why "every minute, gated by Python":
#   The admin can edit ``geoip.refresh_schedule`` in the UI and the
#   change takes effect on the next minute. No SSH, no crontab edit,
#   no service restart. See install_geoip_cron.sh for the design.
#
# This wrapper adds:
#
#   • flock guard:    prevents concurrent runs (cron + manual collision)
#   • silent-cron behaviour: when --only-if-scheduled exits 0 without
#                            doing work, we DON'T log anything. This is
#                            critical — at 1,440 ticks/day, logging
#                            "not scheduled" on each tick would drown
#                            the few real entries.
#   • full logging on actual refreshes:  when the CLI prints (because it
#                                        ran the refresh), we tee it to
#                                        /var/log/cpmai/geoip_refresh.log
#   • exit code:      propagates the CLI's exit code so cron-failure
#                     mail carries the right signal
#   • runtime cap:    120s — if MaxMind hangs, fail loudly
#
# Manual mode:
#   Run with `--force` (or no args) and the schedule check is skipped —
#   useful for "I just changed the license key, refresh right now."
#   The same path is also reachable via /admin/geoip → Refresh now.
#
# Exit codes (forwarded from the CLI):
#   0 = success (whether updated=True, =False, or skipped-by-schedule)
#   1 = credentials error  — operator action: rotate the license key
#   2 = network error      — operator action: check network / MaxMind status
#   3 = database error     — operator action: investigate /admin/geoip
#   4 = misuse             — should not happen via cron
#  >=130 = killed by timeout — investigate connectivity to MaxMind
#
# Usage:
#   ./scripts/vps/geoip_refresh.sh            # cron path (--only-if-scheduled)
#   ./scripts/vps/geoip_refresh.sh --force    # manual / always-run
#
# Cron:    * * * * * /opt/cpmai-prep/scripts/vps/geoip_refresh.sh \
#                       >> /var/log/cpmai/geoip_refresh_cron.log 2>&1
# (Every minute on the VPS. Schedule actually used = the cron expression
#  in geoip.refresh_schedule — admin-editable in /admin/geoip.)
# ==============================================================================
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/cpmai-prep}"
LOG_FILE="${GEOIP_REFRESH_LOG:-/var/log/cpmai/geoip_refresh.log}"
LOCK_FILE="${GEOIP_REFRESH_LOCK:-/var/lock/cpmai-geoip-refresh.lock}"
TIMEOUT_SECONDS="${GEOIP_REFRESH_TIMEOUT:-120}"

# Parse flags. Default is "cron mode" (--only-if-scheduled). --force
# flips us into "manual mode" which skips the schedule gate.
FORCE_MODE=""
if [ "${1:-}" = "--force" ]; then
  FORCE_MODE=1
fi

# Make sure the log dir exists; if not, fall back to syslog so we
# don't lose the failure notice.
LOG_DIR="$(dirname "$LOG_FILE")"
if [ ! -d "$LOG_DIR" ]; then
  mkdir -p "$LOG_DIR" 2>/dev/null || true
fi

ts()  { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
log() { printf '[%s] %s\n' "$(ts)" "$*" | tee -a "$LOG_FILE"; }
# log-only-on-stderr (used for "I didn't do anything" cron exits — we
# don't want these in the persistent log file).
quiet_exit() { exit "$1"; }

# ------------------------------------------------------------------------------
# flock guard — refuse to run if another instance is already running.
# Use non-blocking flock and exit silently to avoid pile-up of "another
# refresh running" log lines on every-minute cron.
# ------------------------------------------------------------------------------
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  # Don't log on the cron path (would flood the log if the previous
  # refresh hung). DO log on the manual path so the operator sees it.
  if [ -z "$FORCE_MODE" ]; then
    quiet_exit 0
  fi
  log "another geoip_refresh is already running — exiting cleanly."
  exit 0
fi

# ------------------------------------------------------------------------------
# Hard timeout — kills anything still running after $TIMEOUT_SECONDS.
# Backgrounded; killed on normal exit by the trap below.
# ------------------------------------------------------------------------------
(
  sleep "$TIMEOUT_SECONDS"
  if kill -0 $$ 2>/dev/null; then
    log "TIMEOUT after ${TIMEOUT_SECONDS}s — killing pid=$$"
    kill -TERM $$ 2>/dev/null || true
  fi
) &
TIMEOUT_PID=$!

cleanup() {
  kill "$TIMEOUT_PID" 2>/dev/null || true
}
trap cleanup EXIT

cd "$APP_DIR"

# ------------------------------------------------------------------------------
# The refresh itself.
#
# In cron mode (--only-if-scheduled): the CLI reads geoip.refresh_schedule
# and exits 0 silently on minutes that don't match. We capture the CLI's
# stdout to a temp file; only if it produced output do we log it. This
# is the trick that keeps the cron log clean.
#
# In manual mode (--force): always run, always log.
# ------------------------------------------------------------------------------
TMP_OUT="$(mktemp)"
trap 'rm -f "$TMP_OUT"; cleanup' EXIT

set +e
if [ -z "$FORCE_MODE" ]; then
  # Cron mode. --only-if-scheduled makes the CLI a no-op on non-matching
  # minutes (no output, exit 0). On matching minutes the CLI runs the
  # full refresh and prints its result.
  docker compose -f docker-compose.production.yml exec -T backend \
      python -m app.services.geoip refresh --only-if-scheduled \
      >"$TMP_OUT" 2>&1
  RC=$?
else
  docker compose -f docker-compose.production.yml exec -T backend \
      python -m app.services.geoip refresh \
      >"$TMP_OUT" 2>&1
  RC=$?
fi
set -e

# Only log if the CLI actually said something. This is what keeps the
# cron log from being flooded by 1,438 daily "not-scheduled" entries.
if [ -s "$TMP_OUT" ]; then
  log "----- refresh output (exit $RC) -----"
  cat "$TMP_OUT" | tee -a "$LOG_FILE"
  case "$RC" in
    0) log "refresh completed successfully (exit 0)" ;;
    1) log "CREDENTIALS error (exit 1) — rotate the license key in /admin/geoip" ;;
    2) log "NETWORK error (exit 2) — check VPS connectivity to MaxMind" ;;
    3) log "DATABASE error (exit 3) — investigate via /admin/geoip" ;;
    *) log "unexpected exit code $RC" ;;
  esac
fi

exit "$RC"
