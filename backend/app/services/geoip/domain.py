"""Domain types for the geoip package.

Three categories of types live here:

  1. ``GeoLocation`` — the OUTPUT of a successful lookup. Frozen dataclass
     so callers can't accidentally mutate it after caching.

  2. ``StatusReport`` / ``RefreshResult`` — operational metadata returned
     by the admin endpoints. Plain dataclasses (not Pydantic) to keep the
     package free of the FastAPI/Pydantic dependency — the
     ``schemas/geoip.py`` Pydantic layer translates these to API shape.

  3. ``GeoIPError`` and subclasses — the error hierarchy used by
     ``refresh_database()``. ``lookup()`` itself never raises (fail-open),
     so this hierarchy is only for the explicit "I asked for a refresh
     and it failed" path.

Why dataclass instead of Pydantic: this package is meant to be
extractable, and Pydantic v2 is a heavyweight dependency for a leaf
package. Dataclasses keep the import graph small and the package
trivially installable into other apps.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------- results

@dataclass(frozen=True)
class GeoLocation:
    """The output of ``lookup(ip)``.

    All fields nullable — a successful lookup may still return a country
    without a city (rural IPs, anonymous proxies registered to a country
    but not a city). Callers should treat each field independently.

    Lat/long are included because they're free (already in the MaxMind
    record) and useful for future map rendering on the admin analytics
    page. Currently the lead enrichment path only persists country + city.
    """
    country: Optional[str] = None       # ISO-3166-1 alpha-2, e.g. "IN"
    city: Optional[str] = None          # English transliteration, e.g. "Bengaluru"
    latitude: Optional[float] = None
    longitude: Optional[float] = None


@dataclass
class StatusReport:
    """Operational snapshot returned by ``get_status()``.

    Used by:
      * /admin/geoip/status — admin UI renders this verbatim
      * /health — embeds a slimmed-down version for ops monitoring

    Field semantics:
      * ``database_present``: True iff the mmdb file exists on disk
      * ``database_path``: where we look for it (always set, even if absent)
      * ``database_size_bytes``: size on disk (None if not present)
      * ``database_mtime``: file mtime as UTC datetime (None if not present)
      * ``database_age_days``: days since mtime (None if not present)
      * ``database_stale``: ``True`` iff age > 35 days (MaxMind publishes
        weekly; >35 days means at least 4 missed refreshes — investigate)
      * ``last_lookup_count``: best-effort process-local counter of lookups
        since last process start (resets on restart; for diagnostic only)
      * ``credentials_configured``: True iff both account_id and license_key
        are non-empty in the settings provider
    """
    database_present: bool = False
    database_path: str = ""
    database_size_bytes: Optional[int] = None
    database_mtime: Optional[datetime] = None
    database_age_days: Optional[float] = None
    database_stale: bool = False
    last_lookup_count: int = 0
    credentials_configured: bool = False


@dataclass
class RefreshResult:
    """Outcome of a ``refresh_database()`` call.

    The cron script and the admin "refresh now" endpoint both consume
    this. ``updated`` is False when MaxMind returns 304 Not Modified
    (we already have the latest); this is a SUCCESS case, not a failure.

    ``bytes_downloaded`` is 0 when not updated. ``database_date`` is the
    YYYYMMDD MaxMind tags the file with; it's the closest thing to a
    "version" the upstream gives us.
    """
    updated: bool
    database_date: Optional[str] = None
    database_size_bytes: int = 0
    bytes_downloaded: int = 0
    elapsed_seconds: float = 0.0
    message: str = ""


# ------------------------------------------------------------------ errors

class GeoIPError(Exception):
    """Base for all errors raised by the geoip package's explicit-failure
    paths (currently: refresh_database, CLI commands).

    ``lookup()`` does NOT raise these — it returns None on any error.
    This hierarchy exists for the operator-facing paths where a clear
    error message matters more than a partial result.
    """


class CredentialsError(GeoIPError):
    """The MaxMind credentials are missing, empty, or rejected (HTTP 401).

    Distinguish this from NetworkError because the operator action is
    different: rotate the license key in /admin/geoip (no SSH needed).
    """


class DatabaseError(GeoIPError):
    """The downloaded file failed integrity verification (sha256 mismatch,
    truncated tarball, or maxminddb can't open the resulting .mmdb).

    Rare but possible — usually a corrupted CDN edge or a partial
    download. The refresh script retries once; persistent failures
    suggest filing a MaxMind support ticket.
    """


class NetworkError(GeoIPError):
    """The download attempt failed with a non-credentials network error
    (DNS, connection refused, timeout, non-200 non-304 status).

    Operator action: check VPS network, MaxMind status page. The cron
    script's exit code surfaces this to system mail / alerting.
    """
