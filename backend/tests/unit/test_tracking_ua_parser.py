"""Unit tests for the hand-rolled UA parser.

We don't have full UA-version-level fidelity (deliberate — see the
docstring on ua_parser.py) but we do guarantee correct bucketing for
the desktop / mobile / tablet × chrome / safari / firefox / edge
matrix that the dashboard groups by.
"""
import pytest

from app.services.tracking.ua_parser import parse


# Most common UAs we see in prod. Sourced from the assistant_logs
# request-header column on representative traffic.

CASES = [
    # ── Desktop
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
     ("desktop", "chrome", "windows")),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
     "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
     ("desktop", "safari", "macos")),
    ("Mozilla/5.0 (X11; Linux x86_64; rv:122.0) Gecko/20100101 Firefox/122.0",
     ("desktop", "firefox", "linux")),
    ("Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/120.0 "
     "Safari/537.36 Edg/120.0.0.0",
     ("desktop", "edge", "windows")),

    # ── Mobile
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
     "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 "
     "Safari/604.1",
     ("mobile", "safari", "ios")),
    ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
     ("mobile", "chrome", "android")),
    ("Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 "
     "(KHTML, like Gecko) SamsungBrowser/23.0 Chrome/115.0.0.0 Mobile "
     "Safari/537.36",
     ("mobile", "samsung", "android")),

    # ── Tablet
    ("Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
     "(KHTML, like Gecko) Version/17.0 Safari/604.1",
     ("tablet", "safari", "ios")),

    # ── Bots
    ("Googlebot/2.1 (+http://www.google.com/bot.html)",
     ("bot", "other", "other")),
    ("Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
     ("bot", "other", "other")),
    ("HeadlessChrome/120.0.0.0",
     ("bot", "chrome", "other")),
]


@pytest.mark.parametrize("ua,expected", CASES)
def test_parse_buckets_known_uas(ua, expected):
    assert parse(ua) == expected


def test_parse_handles_none_and_empty():
    assert parse(None) == ("desktop", "other", "other")
    assert parse("") == ("desktop", "other", "other")


def test_parse_unknown_falls_through_safely():
    # A nonsense UA should not raise and should return the conservative
    # default so dashboards still see a row.
    assert parse("ZZ-totally-not-a-real-UA-1.0") == ("desktop", "other", "other")
