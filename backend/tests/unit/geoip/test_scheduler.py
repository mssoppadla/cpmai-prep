"""Tests for the cron-expression matcher + preview helpers.

The bug shapes we're guarding against:

  1. Drift between the schedule-validator's "what's a valid cron" and
     croniter's actual interpretation. Catch by round-tripping a known
     valid expression and confirming its next-fire times look sane.

  2. Schedules so frequent they'd get us rate-limited by MaxMind. The
     validator caps at MAX_FIRES_PER_DAY (24). Hitting more than that
     must be rejected with a helpful message.

  3. ``is_scheduled_now`` mistakenly returning True on the wrong minute,
     which would cause the cron-hot-path refresh to fire constantly.

  4. ``is_scheduled_now`` raising on a malformed expression instead of
     returning False. The CLI catches via try/except but we want the
     primitive itself to be defensive.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

import pytest

from app.services.geoip.scheduler import (
    DEFAULT_SCHEDULE, MAX_FIRES_PER_DAY,
    human_description, is_scheduled_now, next_run_times,
    validate_expression,
)


# ----------------------------------------------------- is_scheduled_now

def test_is_scheduled_now_matches_default_schedule():
    """The default schedule fires Wed + Sat at 04:17 UTC. A Wednesday
    at 04:17 should match; the same Wednesday at 04:18 should not."""
    # 2026-05-13 is a Wednesday. Confirmed via `cal 5 2026`.
    wed_at_417 = datetime(2026, 5, 13, 4, 17, tzinfo=timezone.utc)
    assert is_scheduled_now(DEFAULT_SCHEDULE, wed_at_417) is True
    assert is_scheduled_now(DEFAULT_SCHEDULE,
                             wed_at_417.replace(minute=18)) is False
    assert is_scheduled_now(DEFAULT_SCHEDULE,
                             wed_at_417.replace(hour=5)) is False


def test_is_scheduled_now_matches_saturday_too():
    """Default schedule also fires Saturday."""
    # 2026-05-16 is a Saturday.
    sat_at_417 = datetime(2026, 5, 16, 4, 17, tzinfo=timezone.utc)
    assert is_scheduled_now(DEFAULT_SCHEDULE, sat_at_417) is True


def test_is_scheduled_now_misses_other_days():
    """Monday at the same time should NOT match Wed+Sat-only schedule."""
    # 2026-05-11 is a Monday.
    mon_at_417 = datetime(2026, 5, 11, 4, 17, tzinfo=timezone.utc)
    assert is_scheduled_now(DEFAULT_SCHEDULE, mon_at_417) is False


def test_is_scheduled_now_ignores_seconds_microseconds():
    """The hot path calls this from cron at :00 of every minute. The
    function must treat any moment WITHIN a minute as the start of that
    minute — so :15s and :45s within the same minute see the same answer."""
    base = datetime(2026, 5, 13, 4, 17, tzinfo=timezone.utc)
    with_seconds = base.replace(second=42, microsecond=123)
    assert is_scheduled_now(DEFAULT_SCHEDULE, base) is True
    assert is_scheduled_now(DEFAULT_SCHEDULE, with_seconds) is True


def test_is_scheduled_now_returns_false_for_invalid_expression():
    """Malformed expression must NOT raise — must just return False.
    The cron-hot-path catches via try/except but the primitive should
    be self-defensive."""
    assert is_scheduled_now("not a cron expression", datetime(2026, 1, 1,
                            tzinfo=timezone.utc)) is False
    assert is_scheduled_now("", datetime(2026, 1, 1,
                            tzinfo=timezone.utc)) is False
    # Out-of-range field values
    assert is_scheduled_now("99 99 * * *", datetime(2026, 1, 1,
                            tzinfo=timezone.utc)) is False


def test_is_scheduled_now_hourly_pattern():
    """A simple hourly schedule fires at minute 0 of every hour."""
    expr = "0 * * * *"
    # Minute 0 → fires
    assert is_scheduled_now(expr,
        datetime(2026, 5, 13, 4, 0, tzinfo=timezone.utc)) is True
    # Minute 30 → doesn't fire
    assert is_scheduled_now(expr,
        datetime(2026, 5, 13, 4, 30, tzinfo=timezone.utc)) is False


# ------------------------------------------------- validate_expression

def test_validate_accepts_default_schedule():
    ok, reason = validate_expression(DEFAULT_SCHEDULE)
    assert ok, f"Default schedule rejected: {reason}"
    assert reason == ""


def test_validate_accepts_common_patterns():
    for expr in ["0 4 * * *",        # daily at 04:00
                 "17 4 * * 3",        # weekly Wed
                 "0 0 1 * *",         # first of month
                 "0 12 * * 1-5"]:     # weekdays at noon
        ok, _ = validate_expression(expr)
        assert ok, f"{expr} should be valid"


def test_validate_rejects_empty():
    ok, reason = validate_expression("")
    assert not ok
    assert "empty" in reason.lower()


def test_validate_rejects_non_string():
    ok, _ = validate_expression(None)  # type: ignore[arg-type]
    assert not ok
    ok, _ = validate_expression(42)  # type: ignore[arg-type]
    assert not ok


def test_validate_rejects_malformed():
    """Garbage strings must be rejected with a parse error message."""
    for bad in ["not a cron",
                "* * *",            # too few fields
                "99 99 * * *",
                "*/0 * * * *"]:     # divide-by-zero
        ok, reason = validate_expression(bad)
        assert not ok, f"{bad!r} should be invalid"
        assert reason  # non-empty


def test_validate_rejects_too_frequent():
    """Every-minute (1440 fires/day) blows the MAX_FIRES_PER_DAY cap."""
    ok, reason = validate_expression("* * * * *")
    assert not ok
    assert f"{MAX_FIRES_PER_DAY}" in reason
    assert "wasteful" in reason.lower() or "rate-limit" in reason.lower()


def test_validate_rejects_unreasonably_long_string():
    """A 1000-char expression is obvious garbage."""
    ok, reason = validate_expression("0 " * 1000)
    assert not ok


def test_validate_accepts_hourly_at_the_max():
    """Hourly = 24 fires/day = exactly at the cap. Must be accepted."""
    ok, _ = validate_expression("0 * * * *")
    assert ok


# --------------------------------------------------------- next_run_times

def test_next_run_times_returns_requested_count():
    after = datetime(2026, 5, 13, 0, 0, tzinfo=timezone.utc)
    runs = next_run_times(DEFAULT_SCHEDULE, count=3, after=after)
    assert len(runs) == 3


def test_next_run_times_returns_chronological_order():
    after = datetime(2026, 5, 13, 0, 0, tzinfo=timezone.utc)
    runs = next_run_times(DEFAULT_SCHEDULE, count=5, after=after)
    for i in range(1, len(runs)):
        assert runs[i] > runs[i - 1]


def test_next_run_times_default_schedule_lands_on_wed_or_sat():
    """The default schedule's next runs are always Wed (2) or Sat (5).
    weekday(): Mon=0, Sun=6 — so Wed=2, Sat=5."""
    runs = next_run_times(DEFAULT_SCHEDULE, count=5)
    for run in runs:
        assert run.weekday() in (2, 5), (
            f"Run {run} on weekday={run.weekday()} (expected Wed=2 or Sat=5)")
        assert run.hour == 4
        assert run.minute == 17


def test_next_run_times_returns_empty_on_invalid_expression():
    assert next_run_times("not a cron", count=3) == []
    assert next_run_times("", count=3) == []


def test_next_run_times_count_zero_returns_empty():
    runs = next_run_times(DEFAULT_SCHEDULE, count=0)
    assert runs == []


# --------------------------------------------------- human_description

def test_human_description_known_patterns():
    """Common defaults render as human language, not the raw cron."""
    out = human_description("17 4 * * 3,6")
    assert "Wed" in out or "Sat" in out
    assert "04:17" in out

    out = human_description("0 4 * * *")
    assert "04:00" in out or "every day" in out.lower()


def test_human_description_unknown_pattern_falls_back():
    """Custom expressions echo back rather than guessing — the next-
    runs preview is the authoritative sanity check."""
    out = human_description("42 7 * * 2,4")
    assert "42 7 * * 2,4" in out
