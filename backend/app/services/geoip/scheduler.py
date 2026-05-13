"""Cron-expression matching + preview for the admin-configurable
refresh schedule.

The flow this module supports:

  Cron on the VPS fires every minute. The refresh script invokes
  ``python -m app.services.geoip refresh --only-if-scheduled``. The CLI
  reads ``geoip.refresh_schedule`` from settings and asks this module
  "does the configured cron expression fire at THIS exact minute?".
  If yes → proceed with the download. If no → exit 0 silently.

  When the admin edits the schedule in /admin/geoip, the change takes
  effect on the very next minute. No SSH, no crontab edit, no restart.

Why we use this indirection at all:
  cron itself reads from /etc/crontab and can't pull from our DB. By
  keeping the *crontab entry* static (every minute) and putting the
  decision logic in Python with settings-driven schedule, we get a
  fully admin-editable scheduler with zero deploy / SSH steps.

Public API
----------
``is_scheduled_now(expr, when=None)`` -> bool
    The hot-path check. Called once per cron tick.

``validate_expression(expr)`` -> (bool, str)
    Settings validator. Returns (ok, reason). Reason is empty on ok.

``next_run_times(expr, count=3, after=None)`` -> list[datetime]
    UI helper for the admin "next 3 scheduled runs" preview.

``human_description(expr)`` -> str
    Best-effort human-readable summary for the admin UI.

Sanity caps
-----------
The validator rejects expressions that would fire more than
``MAX_FIRES_PER_DAY`` times. This stops a fat-fingered ``* * * * *``
(every minute = 1440 fires/day = MaxMind would block us within hours)
from sneaking through. The default 24 is comfortably above any sane
schedule.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional

try:
    from croniter import croniter, CroniterBadCronError
except ImportError:  # pragma: no cover
    croniter = None  # type: ignore
    CroniterBadCronError = Exception  # type: ignore


# Maximum fires per 24h we accept. MaxMind publishes 2x/week, so even
# daily is overkill. Cap at 24/day (hourly) — anything more is almost
# certainly an admin misconfig and would risk rate-limit / abuse from
# MaxMind's side.
MAX_FIRES_PER_DAY = 24


# Default schedule, baked here AND in default_settings.json. We keep
# both in sync because (a) the seed handles fresh installs, and (b) the
# CLI falls back to this constant when the setting somehow ends up
# unset on a running system — preferring to refresh on the default
# schedule over silently refusing.
DEFAULT_SCHEDULE = "17 4 * * 3,6"


def is_scheduled_now(expr: str, when: Optional[datetime] = None) -> bool:
    """Return True iff the cron expression would fire at the given minute.

    Args:
        expr: A 5-field cron expression (minute hour day-of-month month
              day-of-week). Standard syntax (``*``, ``,``, ``-``, ``/``).
        when: The "current" datetime to test against. Defaults to UTC
              now. Truncated to minute precision internally so that
              calls during the same minute return consistent results.

    Returns:
        True if the cron expression fires at exactly that minute. False
        on any error (invalid expression, missing croniter — defensive,
        the CLI catches and logs).
    """
    if croniter is None:
        return False
    if when is None:
        when = datetime.now(timezone.utc)
    # Strip seconds + microseconds so two invocations within the same
    # minute see identical inputs. Belt-and-suspenders since cron
    # invokes us at :00 of every minute.
    when = when.replace(second=0, microsecond=0)
    try:
        return croniter.match(expr, when)
    except (CroniterBadCronError, ValueError, KeyError):
        return False


def validate_expression(expr: str) -> tuple[bool, str]:
    """Validate a cron expression for use as a refresh schedule.

    Returns:
        (True, "") if valid AND fires <= MAX_FIRES_PER_DAY times/day.
        (False, "<reason>") otherwise. The reason is suitable for
        surfacing to an admin in an error toast.
    """
    if croniter is None:
        return False, "Server-side cron parser is not installed."
    if not isinstance(expr, str):
        return False, "Schedule must be a string."
    expr = expr.strip()
    if not expr:
        return False, "Schedule cannot be empty."
    # Reject schedules longer than a sane bound. croniter parses
    # arbitrarily long strings but they'd be a misconfig.
    if len(expr) > 200:
        return False, "Schedule expression is unreasonably long."
    try:
        # Validation: try to construct a croniter and ask for next run.
        # If the expression is malformed this raises.
        it = croniter(expr, datetime(2026, 1, 1, tzinfo=timezone.utc))
        first = it.get_next(datetime)
        # Sanity-cap: count fires in a 24h window starting at the first
        # fire. Reject if too many. We sample the next 24h, NOT a
        # rolling window — but for the typical "schedules like cron"
        # case this is exact (cron expressions repeat daily or longer).
        end = first + timedelta(hours=24)
        fires = 1
        while True:
            nxt = it.get_next(datetime)
            if nxt >= end:
                break
            fires += 1
            if fires > MAX_FIRES_PER_DAY:
                return False, (
                    f"Schedule fires more than {MAX_FIRES_PER_DAY} times "
                    "in 24 hours. The free GeoLite2-City updates twice "
                    "weekly — refreshing more than daily is wasteful and "
                    "may be rate-limited by MaxMind. Use a coarser schedule."
                )
    except (CroniterBadCronError, ValueError, KeyError) as exc:
        return False, f"Invalid cron expression: {exc}"
    return True, ""


def next_run_times(
    expr: str, count: int = 3, after: Optional[datetime] = None,
) -> list[datetime]:
    """Return the next ``count`` times this schedule will fire.

    Used by the admin /admin/geoip page so the operator can sanity-check
    a custom schedule before saving — "you said '0 12 * * 1' and it
    means: Monday next at 12:00, Monday after at 12:00, ...".

    Returns an empty list on any error (invalid expression). Callers
    render that as "no upcoming runs — check the expression."
    """
    if croniter is None:
        return []
    if after is None:
        after = datetime.now(timezone.utc)
    try:
        it = croniter(expr, after)
        return [it.get_next(datetime) for _ in range(max(0, count))]
    except (CroniterBadCronError, ValueError, KeyError):
        return []


def human_description(expr: str) -> str:
    """Best-effort human-readable summary for the admin UI.

    We hand-roll a few well-known patterns rather than pull a dedicated
    cron-to-prose library (cron_descriptor adds ~1MB of locale data).
    For unknown patterns we return the raw expression. The "next runs"
    list in the UI is the authoritative sanity check anyway.
    """
    expr = (expr or "").strip()
    # The defaults we ship with — most users won't deviate.
    common = {
        "17 4 * * 3,6":   "Wednesdays + Saturdays at 04:17 UTC",
        "17 4 * * 3":     "Every Wednesday at 04:17 UTC",
        "17 4 * * 6":     "Every Saturday at 04:17 UTC",
        "0 * * * *":      "Every hour, on the hour",
        "0 4 * * *":      "Every day at 04:00 UTC",
        "0 4 * * 0":      "Every Sunday at 04:00 UTC",
        "0 0 1 * *":      "First day of every month at midnight UTC",
    }
    if expr in common:
        return common[expr]
    return f"Custom schedule: {expr}"
