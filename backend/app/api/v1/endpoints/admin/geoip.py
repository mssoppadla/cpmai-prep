"""Admin endpoints for the GeoIP feature.

Four endpoints:

  GET   /admin/geoip/status        Status snapshot (UI dashboard)
  POST  /admin/geoip/test-key      "Test connection" button
  POST  /admin/geoip/refresh-now   Manual refresh trigger
  POST  /admin/geoip/lookup        Debug: resolve a specific IP

All four are admin-gated by the router-level dependency (``admin_router``
has ``Depends(get_admin_user)``).

Rate-limit discipline
---------------------
* test-key:    5/hour — prevents brute force on the license key via
                       a fast oracle (MaxMind would also lock the account
                       but we don't want to find that out).
* refresh-now: 3/hour — MaxMind publishes weekly, so manual refreshes
                       should be rare. The limit is generous enough for
                       "I just rotated the key, let me re-pull" but
                       prevents accidental thundering herd.
* lookup:      30/min — generous, just a sanity backstop. Lookups are
                       cheap (in-process mmap, no network).
* status:      no limit — pure in-process read.

Why POST for lookup/test-key/refresh-now
----------------------------------------
* lookup: takes a body parameter (``ip``), which is a POST convention
  even though semantically it's idempotent. Avoids URL-leaking IPs into
  proxy logs.
* test-key, refresh-now: side-effecting (test makes an outbound HTTP
  call; refresh writes to disk). POST is correct.
"""
import time
from typing import Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.deps import get_db, get_admin_user
from app.core.exceptions import AppError
from app.core.limiter import limiter


# Custom AppError subclasses for the three geoip refresh failure modes.
# Defined here (not in core/exceptions.py) because they're specific to
# this endpoint module; promoting them to core would expand the surface
# without benefit.
class _GeoIPCredentialsError(AppError):
    code = "geoip_credentials"

    def __init__(self, message: str):
        super().__init__(message, status_code=400)


class _GeoIPNetworkError(AppError):
    code = "geoip_network"

    def __init__(self, message: str):
        super().__init__(message, status_code=502)


class _GeoIPDatabaseError(AppError):
    code = "geoip_database"

    def __init__(self, message: str):
        super().__init__(message, status_code=500)
from app.models.user import User
from app.schemas.geoip import (
    GeoIPLookupIn, GeoIPLookupOut, GeoIPRefreshOut,
    GeoIPSchedulePreviewIn, GeoIPSchedulePreviewOut,
    GeoIPStatusOut, GeoIPTestKeyOut,
)
from app.services.geoip import (
    CredentialsError, DatabaseError, NetworkError,
    get_status, lookup as do_lookup, refresh_database,
)
from app.services.geoip.protocols import SettingsKeys
from app.services.geoip.refresh import MAXMIND_DOWNLOAD_URL, EDITION_ID, USER_AGENT
from app.services.geoip.scheduler import (
    DEFAULT_SCHEDULE, human_description, next_run_times, validate_expression,
)
from app.services.geoip.settings import default_provider

log = structlog.get_logger("admin.geoip")

router = APIRouter()


# ----------------------------------------------------------------- status
@router.get("/status", response_model=GeoIPStatusOut)
def geoip_status():
    """Snapshot for the admin dashboard. Read-only; never fails.

    Includes the current refresh schedule + a small preview of upcoming
    runs so the admin /admin/geoip page can render the operational
    state in one round-trip.
    """
    out = GeoIPStatusOut.from_domain(get_status())
    # Schedule preview — uses the stored setting or the package default
    # if unset. next_run_times returns [] on parse failure, which is the
    # right "the schedule is broken" signal for the UI.
    expr = default_provider.get(SettingsKeys.REFRESH_SCHEDULE) or DEFAULT_SCHEDULE
    out.refresh_schedule = expr
    out.refresh_schedule_human = human_description(expr)
    out.refresh_schedule_next_runs = next_run_times(expr, count=3)
    out.refresh_enabled = default_provider.get_bool(
        SettingsKeys.REFRESH_ENABLED, True)
    return out


# ------------------------------------------------------------- schedule-preview
@router.post("/schedule-preview", response_model=GeoIPSchedulePreviewOut)
def geoip_schedule_preview(payload: GeoIPSchedulePreviewIn):
    """Validate + preview a candidate schedule WITHOUT persisting it.

    The admin UI calls this as the operator types a custom cron
    expression. Returns:
      * ok=True + human + next_runs    — the expression is valid
      * ok=False + reason              — invalid / violates a sanity cap

    Why a dedicated endpoint instead of just relying on PATCH:
    PATCH validates and saves atomically. Operators want to SEE what
    a custom schedule will do BEFORE committing. This endpoint gives
    them that without polluting the settings table with experiments.
    """
    ok, reason = validate_expression(payload.expression)
    if not ok:
        return GeoIPSchedulePreviewOut(
            expression=payload.expression, ok=False, reason=reason,
        )
    return GeoIPSchedulePreviewOut(
        expression=payload.expression,
        ok=True,
        human=human_description(payload.expression),
        next_runs=next_run_times(payload.expression, count=payload.count),
    )


# --------------------------------------------------------------- test-key
@router.post("/test-key", response_model=GeoIPTestKeyOut)
@limiter.limit("5/hour")
def geoip_test_key(request: Request,
                   db: Session = Depends(get_db),
                   admin: User = Depends(get_admin_user)):
    """Verify the stored MaxMind credentials by issuing a HEAD request.

    Side-effects:
      * audit_log entry "geoip.test_key" with ok=True/False (NEVER the key)

    Why HEAD and not GET: we only want to verify auth, not pull the
    whole tarball. MaxMind serves a HEAD with the same auth shape and
    returns 200 + the size/etag headers.
    """
    account_id = default_provider.get(SettingsKeys.MAXMIND_ACCOUNT_ID)
    license_key = default_provider.get(SettingsKeys.MAXMIND_LICENSE_KEY)
    if not account_id or not license_key:
        audit_log(db, admin.id, "geoip.test_key",
                  {"ok": False, "reason": "credentials_unset"})
        return GeoIPTestKeyOut(
            ok=False,
            message="MaxMind credentials are not configured. Set "
                    f"{SettingsKeys.MAXMIND_ACCOUNT_ID} and "
                    f"{SettingsKeys.MAXMIND_LICENSE_KEY} below.",
        )

    params = {"edition_id": EDITION_ID, "suffix": "tar.gz"}
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.head(MAXMIND_DOWNLOAD_URL,
                               params=params,
                               auth=(account_id, license_key),
                               headers={"User-Agent": USER_AGENT},
                               follow_redirects=True)
    except httpx.HTTPError as exc:
        audit_log(db, admin.id, "geoip.test_key",
                  {"ok": False, "reason": "network",
                   "exception": type(exc).__name__})
        return GeoIPTestKeyOut(
            ok=False,
            message=f"Network error reaching MaxMind: {type(exc).__name__}.",
        )

    if resp.status_code == 401:
        audit_log(db, admin.id, "geoip.test_key",
                  {"ok": False, "status_code": 401})
        return GeoIPTestKeyOut(
            ok=False, status_code=401,
            message="MaxMind rejected the license key. Rotate it at "
                    "maxmind.com → My License Keys, then update the "
                    "value below.",
        )

    if resp.status_code != 200:
        audit_log(db, admin.id, "geoip.test_key",
                  {"ok": False, "status_code": resp.status_code})
        return GeoIPTestKeyOut(
            ok=False, status_code=resp.status_code,
            message=f"Unexpected response from MaxMind: HTTP {resp.status_code}.",
        )

    # Parse the filename from Content-Disposition to surface the latest
    # DB date in the UI — e.g. "filename=GeoLite2-City_20260512.tar.gz".
    db_date = _parse_db_date(resp.headers.get("content-disposition", ""))
    audit_log(db, admin.id, "geoip.test_key",
              {"ok": True, "db_date": db_date})
    return GeoIPTestKeyOut(
        ok=True, status_code=200,
        message=f"Credentials accepted. Latest DB date: {db_date or 'unknown'}.",
        latest_db_date=db_date,
    )


# ------------------------------------------------------------- refresh-now
@router.post("/refresh-now", response_model=GeoIPRefreshOut)
@limiter.limit("3/hour")
def geoip_refresh_now(request: Request,
                      db: Session = Depends(get_db),
                      admin: User = Depends(get_admin_user)):
    """Trigger an immediate refresh. Maps geoip errors to clean 4xx/5xx.

    The cron path uses the CLI; the admin UI uses this endpoint. Same
    underlying logic, different surfaces.
    """
    start = time.monotonic()
    try:
        result = refresh_database()
    except CredentialsError as exc:
        audit_log(db, admin.id, "geoip.refresh_now",
                  {"ok": False, "kind": "credentials"})
        raise _GeoIPCredentialsError(str(exc))
    except NetworkError as exc:
        audit_log(db, admin.id, "geoip.refresh_now",
                  {"ok": False, "kind": "network"})
        raise _GeoIPNetworkError(str(exc))
    except DatabaseError as exc:
        audit_log(db, admin.id, "geoip.refresh_now",
                  {"ok": False, "kind": "database"})
        raise _GeoIPDatabaseError(str(exc))

    audit_log(db, admin.id, "geoip.refresh_now",
              {"ok": True, "updated": result.updated,
               "db_date": result.database_date,
               "elapsed": round(time.monotonic() - start, 3)})
    return GeoIPRefreshOut.from_domain(result)


# --------------------------------------------------------------- lookup
@router.post("/lookup", response_model=GeoIPLookupOut)
@limiter.limit("30/minute")
def geoip_lookup(request: Request, payload: GeoIPLookupIn):
    """Debug endpoint: resolve a specific IP. Useful for verifying
    "the prod DB has data for this country" without SSHing in."""
    geo = do_lookup(payload.ip)
    return GeoIPLookupOut.from_domain(payload.ip, geo)


# ----------------------------------------------------------------- utils
def _parse_db_date(content_disposition: str) -> Optional[str]:
    """Extract YYYYMMDD from ``filename=GeoLite2-City_20260512.tar.gz``."""
    if "GeoLite2-City_" not in content_disposition:
        return None
    try:
        slug = content_disposition.split("GeoLite2-City_", 1)[1]
        date_part = slug.split(".", 1)[0]
        # Tolerate underscores in unexpected places.
        if date_part.isdigit() and len(date_part) == 8:
            return date_part
    except (IndexError, AttributeError):
        pass
    return None
