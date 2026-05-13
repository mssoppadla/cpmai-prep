"""Pydantic shapes for the /admin/geoip endpoints.

These are deliberately separate from the geoip package's domain
dataclasses (``GeoLocation``, ``StatusReport``, ``RefreshResult``) so
that:

  * The geoip package stays Pydantic-free (small dependency footprint,
    easier to extract).
  * The HTTP contract can evolve independently from the internal types
    (e.g. add presentation fields like ``database_age_human``).

Each schema below has a `from_domain()` classmethod that translates the
internal type into the HTTP shape, keeping the mapping in one place.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.services.geoip.domain import (
    GeoLocation, StatusReport, RefreshResult,
)


class GeoIPStatusOut(BaseModel):
    database_present: bool
    database_path: str
    database_size_bytes: Optional[int] = None
    database_size_human: Optional[str] = None
    database_mtime: Optional[datetime] = None
    database_age_days: Optional[float] = None
    database_stale: bool = False
    last_lookup_count: int = 0
    credentials_configured: bool = False
    # Schedule preview, surfaced on /admin/geoip so the operator can
    # see the current cron expression + the next few runs without
    # leaving the page. Populated by the endpoint, not the domain
    # StatusReport — schedule concerns live one layer up from lookup.
    refresh_schedule: Optional[str] = None
    refresh_schedule_human: Optional[str] = None
    refresh_schedule_next_runs: list[datetime] = []
    refresh_enabled: bool = True

    @classmethod
    def from_domain(cls, report: StatusReport) -> "GeoIPStatusOut":
        return cls(
            database_present=report.database_present,
            database_path=report.database_path,
            database_size_bytes=report.database_size_bytes,
            database_size_human=_human_bytes(report.database_size_bytes)
                if report.database_size_bytes is not None else None,
            database_mtime=report.database_mtime,
            database_age_days=report.database_age_days,
            database_stale=report.database_stale,
            last_lookup_count=report.last_lookup_count,
            credentials_configured=report.credentials_configured,
        )


class GeoIPSchedulePreviewIn(BaseModel):
    """Body for ``POST /admin/geoip/schedule-preview``.

    Lets the admin UI ask "if I saved THIS expression, when would it
    fire next?" without actually persisting — so the operator can
    sanity-check a custom schedule before clicking save.
    """
    expression: str = Field(min_length=1, max_length=200)
    count: int = Field(default=5, ge=1, le=20)


class GeoIPSchedulePreviewOut(BaseModel):
    """Result of a schedule-preview request.

    ``ok=True`` with populated ``next_runs`` means the expression is
    valid and will fire at those times. ``ok=False`` with ``reason``
    means the expression is malformed or violates a sanity cap (e.g.
    too many fires per day); the UI shows ``reason`` to the operator.
    """
    expression: str
    ok: bool
    reason: str = ""
    human: str = ""
    next_runs: list[datetime] = []


class GeoIPRefreshOut(BaseModel):
    updated: bool
    database_date: Optional[str] = None
    database_size_bytes: int = 0
    bytes_downloaded: int = 0
    elapsed_seconds: float = 0.0
    message: str = ""

    @classmethod
    def from_domain(cls, result: RefreshResult) -> "GeoIPRefreshOut":
        return cls(
            updated=result.updated,
            database_date=result.database_date,
            database_size_bytes=result.database_size_bytes,
            bytes_downloaded=result.bytes_downloaded,
            elapsed_seconds=round(result.elapsed_seconds, 3),
            message=result.message,
        )


class GeoIPLookupOut(BaseModel):
    ip: str
    found: bool
    country: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @classmethod
    def from_domain(cls, ip: str, geo: Optional[GeoLocation]) -> "GeoIPLookupOut":
        if geo is None:
            return cls(ip=ip, found=False)
        return cls(
            ip=ip, found=True,
            country=geo.country, city=geo.city,
            latitude=geo.latitude, longitude=geo.longitude,
        )


class GeoIPTestKeyOut(BaseModel):
    """Outcome of the "Test connection" button in the admin UI."""
    ok: bool
    status_code: Optional[int] = None
    message: str
    # Only set on ok=True. Helpful for the admin UI's "yes the key
    # really works" confirmation.
    latest_db_date: Optional[str] = None


class GeoIPLookupIn(BaseModel):
    ip: str = Field(min_length=1, max_length=45)   # IPv6 max is 39, headroom


def _human_bytes(n: Optional[int]) -> Optional[str]:
    if n is None:
        return None
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KiB"
    return f"{n / (1024 * 1024):.1f} MiB"
