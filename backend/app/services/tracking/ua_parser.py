"""Minimal User-Agent parser.

We deliberately do NOT depend on the `user-agents` PyPI package — it
ships a 1.5MB regex bundle that's overkill for our needs and adds an
import-time cost to every request. Our dashboards only ever need three
buckets each for device / browser / os, so a hand-rolled set of
substring checks is faster, lighter, and easier to update when (say)
"Arc" or a new mobile browser starts showing up in logs.

If we ever want UA-version-level granularity (per-Chrome-major rollups),
swap this module for the `user-agents` package — the call sites only
look at the three string buckets returned here.
"""
from __future__ import annotations

from typing import Literal


Device  = Literal["desktop", "mobile", "tablet", "bot"]
Browser = Literal["chrome", "safari", "firefox", "edge", "opera",
                   "samsung", "arc", "other"]
OS      = Literal["windows", "macos", "linux", "ios", "android",
                   "chromeos", "other"]


# Common bot UA fragments. Not exhaustive — anything we miss falls
# through as the actual device type, which is fine for our use case
# (we'd rather count an unknown bot than miss a real visitor).
_BOT_FRAGMENTS = (
    "bot", "crawler", "spider", "headless", "facebookexternalhit",
    "preview", "slurp", "scraper", "wget", "curl/", "httpclient",
    "monitoring", "uptimerobot", "pingdom",
)


def parse(ua: str | None) -> tuple[Device, Browser, OS]:
    """Return ``(device, browser, os)`` for the given UA string.

    Safe for empty / None input — returns the conservative
    ``("desktop", "other", "other")`` so dashboards still see a row.
    """
    if not ua:
        return "desktop", "other", "other"
    ua_lower = ua.lower()

    # Bot detection runs FIRST. A headless-Chrome run shouldn't show
    # up in "Chrome on Desktop" rollups — it should show up as a bot
    # so operators can subtract it from real-user counts.
    if any(frag in ua_lower for frag in _BOT_FRAGMENTS):
        return "bot", _browser(ua_lower), _os(ua_lower)

    device: Device
    if "tablet" in ua_lower or "ipad" in ua_lower:
        device = "tablet"
    elif "mobi" in ua_lower or "android" in ua_lower or "iphone" in ua_lower:
        device = "mobile"
    else:
        device = "desktop"

    return device, _browser(ua_lower), _os(ua_lower)


def _browser(ua_lower: str) -> Browser:
    # Order matters. Edge UA contains "Chrome"; Opera contains "Chrome";
    # SamsungBrowser contains "Chrome"; Arc contains "Chrome". The more
    # specific must win.
    if "edg/" in ua_lower or "edge/" in ua_lower:
        return "edge"
    if "opr/" in ua_lower or "opera" in ua_lower:
        return "opera"
    if "samsungbrowser" in ua_lower:
        return "samsung"
    if "arc/" in ua_lower:
        return "arc"
    if "firefox" in ua_lower or "fxios" in ua_lower:
        return "firefox"
    if "chrome" in ua_lower or "crios" in ua_lower:
        return "chrome"
    # Safari last because Chrome's UA also contains "Safari".
    if "safari" in ua_lower:
        return "safari"
    return "other"


def _os(ua_lower: str) -> OS:
    # iOS before macOS — iPhone UA contains "Mac OS X" string but is iOS.
    if "iphone" in ua_lower or "ipad" in ua_lower or "ipod" in ua_lower:
        return "ios"
    if "android" in ua_lower:
        return "android"
    if "cros" in ua_lower:
        return "chromeos"
    if "windows" in ua_lower:
        return "windows"
    if "mac os" in ua_lower or "macintosh" in ua_lower:
        return "macos"
    if "linux" in ua_lower:
        return "linux"
    return "other"
