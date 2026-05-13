"""IP-to-location lookup with mmap-backed mmdb + mtime hot-reload.

Why a class with an internal cache
----------------------------------
The mmdb file is 50-80MB; opening it on every request would be slow
and wasteful. ``maxminddb.open_database`` returns a Reader that mmaps
the file — fast for repeated lookups. We hold a single Reader per
process and refresh it ONLY when the file's mtime has changed.

Hot-reload is what makes the recurring cron refresh transparent: the
cron (Wed + Sat 04:17 UTC, aligned with MaxMind's Tue/Fri release
cadence) writes a new file, mtime advances, the next request notices
and re-opens. No app restart, no health-check blip.

Concurrency
-----------
The mmap Reader itself is thread-safe for reads. The reload logic uses
a single lock to avoid two threads racing to reopen the file at once.
Reads never block on each other.

Fail-open contract
------------------
This module's ``lookup()`` NEVER raises. Every failure path returns
None and logs at ``warning`` (mmdb missing) or ``debug`` (private IP,
not-found). The HTTP request path must continue regardless of GeoIP
state — that's the whole point of fail-open.
"""
from __future__ import annotations
import ipaddress
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog

from app.services.geoip.domain import GeoLocation, StatusReport
from app.services.geoip.protocols import SettingsKeys, SettingsProvider
from app.services.geoip.settings import default_provider

log = structlog.get_logger("geoip.lookup")


# The canonical install path for the mmdb file. Kept here (not in a
# settings key) because changing it requires also updating the
# install/refresh scripts — keeping it pinned in source means one place
# to grep.
DEFAULT_DB_PATH = Path("/srv/cpmai/geoip/GeoLite2-City.mmdb")

# >= this many days since the last successful refresh is "stale" — we
# surface it in the admin UI / health endpoint to prompt investigation.
# MaxMind publishes weekly; 35 days = at least 4 missed refreshes.
STALE_THRESHOLD_DAYS = 35


class MaxMindLookup:
    """The default lookup implementation. One instance per process.

    Public API:
        lookup(ip)       -> GeoLocation | None  — fail-open
        get_status()     -> StatusReport
        invalidate()     -> None                — force re-open on next call

    Note: maxminddb is imported lazily so the package can be imported
    even when the lib isn't installed (e.g. during tests that don't
    need geoip but still import models that touch this module).
    """

    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,
        *,
        settings: SettingsProvider = default_provider,
    ):
        self._db_path = db_path
        self._settings = settings
        self._reader = None
        self._reader_mtime: Optional[float] = None
        self._lock = threading.Lock()
        self._lookup_count = 0

    # -------------------------------------------------- lookups (hot path)

    def lookup(self, ip: Optional[str]) -> Optional[GeoLocation]:
        """Resolve ``ip`` to a GeoLocation, or None on any miss/failure.

        Returns None for:
          * ``ip is None`` or empty string
          * ``ip`` is private/loopback/reserved (RFC 1918, 127.0.0.0/8, etc.)
          * mmdb file not present on disk
          * mmdb has no record for this IP (rare but real for very
            recent IPv6 allocations)
          * any other internal error — caught broad-except by design.
        """
        if not ip:
            return None
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return None
        # Private addresses: don't even attempt — saves a syscall and
        # makes test fixtures (using 127.0.0.1) deterministic.
        if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
            return None

        reader = self._get_reader()
        if reader is None:
            return None
        try:
            record = reader.get(ip)
        except Exception as exc:
            # maxminddb can raise on a truly malformed IP that got past
            # ipaddress (extremely rare), or if the file went away
            # mid-read. Fail-open.
            log.warning("geoip.lookup_failed", ip=ip, error=str(exc))
            return None
        finally:
            # Increment after the lookup attempt regardless of outcome —
            # this counter tracks load, not success rate.
            self._lookup_count += 1
        if not record:
            return None
        return _record_to_geolocation(record)

    def get_status(self) -> StatusReport:
        """Return a status snapshot for admin UI / health endpoint.

        Never raises. If the file is missing, returns a report with
        ``database_present=False`` and the rest defaulted.
        """
        report = StatusReport(database_path=str(self._db_path))
        report.last_lookup_count = self._lookup_count
        # Only the license_key is REQUIRED for the public direct-download
        # URL. account_id is stored as metadata (used by geoipupdate if/
        # when we adopt it) but not consulted by refresh.py. So
        # "credentials configured" means just "license_key is set".
        report.credentials_configured = bool(
            self._settings.get(SettingsKeys.MAXMIND_LICENSE_KEY)
        )
        if not self._db_path.exists():
            return report
        try:
            stat = self._db_path.stat()
        except OSError:
            return report
        report.database_present = True
        report.database_size_bytes = stat.st_size
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        report.database_mtime = mtime
        age = (datetime.now(timezone.utc) - mtime).total_seconds() / 86400.0
        report.database_age_days = round(age, 2)
        report.database_stale = age >= STALE_THRESHOLD_DAYS
        return report

    def invalidate(self) -> None:
        """Drop the cached reader. Next lookup() reopens the file.

        Called by the refresh script after a successful install to
        guarantee that even if mtime granularity is coarse (some
        filesystems are second-precision), the new DB is used
        immediately.
        """
        with self._lock:
            self._close_reader()

    # ----------------------------------------------------- reader plumbing

    def _get_reader(self):
        """Return the current Reader, re-opening if the file changed."""
        try:
            mtime = self._db_path.stat().st_mtime
        except OSError:
            # File doesn't exist. Drop any cached reader and return None.
            if self._reader is not None:
                with self._lock:
                    self._close_reader()
            return None

        if self._reader is not None and self._reader_mtime == mtime:
            return self._reader

        with self._lock:
            # Re-check under lock — another thread may have already
            # re-opened the reader while we waited.
            if self._reader is not None and self._reader_mtime == mtime:
                return self._reader
            self._close_reader()
            try:
                import maxminddb  # lazy import
                self._reader = maxminddb.open_database(str(self._db_path))
                self._reader_mtime = mtime
                log.info("geoip.reader_opened",
                         path=str(self._db_path), mtime=mtime)
            except Exception as exc:
                log.warning("geoip.reader_open_failed",
                            path=str(self._db_path), error=str(exc))
                self._reader = None
                self._reader_mtime = None
            return self._reader

    def _close_reader(self) -> None:
        """Close the existing reader if any. Must be called under lock."""
        if self._reader is not None:
            try:
                self._reader.close()
            except Exception:
                pass
            self._reader = None
            self._reader_mtime = None


def _record_to_geolocation(record: dict) -> GeoLocation:
    """Map a MaxMind GeoLite2-City record to our GeoLocation dataclass.

    MaxMind's record shape (relevant pieces):
        {
          "country": {"iso_code": "IN", "names": {"en": "India", ...}},
          "city":    {"names": {"en": "Bengaluru", ...}},
          "location": {"latitude": 12.97, "longitude": 77.59, ...},
        }

    Every key is optional — anonymous proxies have ``country`` but no
    ``city``, very-new IPv6 blocks have neither. We extract defensively.
    """
    country = (record.get("country") or {}).get("iso_code")
    city = ((record.get("city") or {}).get("names") or {}).get("en")
    location = record.get("location") or {}
    latitude = location.get("latitude")
    longitude = location.get("longitude")
    return GeoLocation(
        country=country,
        city=city,
        latitude=latitude,
        longitude=longitude,
    )


# Module-level singleton — the public ``lookup()`` and ``get_status()``
# helpers go through this. Tests can construct their own ``MaxMindLookup``
# with a different ``db_path`` to point at a fixture.
_default_lookup = MaxMindLookup()


def lookup(ip: Optional[str]) -> Optional[GeoLocation]:
    """Module-level convenience wrapper around the default lookup."""
    return _default_lookup.lookup(ip)


def get_status() -> StatusReport:
    """Module-level convenience wrapper for admin/health endpoints."""
    return _default_lookup.get_status()


def invalidate_default() -> None:
    """Force the default lookup to drop its cached reader. Called by
    the refresh path so a brand-new mmdb is picked up even on
    filesystems where mtime granularity is coarse."""
    _default_lookup.invalidate()
