"""GeoIP enrichment package — IP → (country, city) lookup with admin-
configurable MaxMind credentials and hot-reloadable database file.

Public API (the only symbols callers outside this package should touch):

    from app.services.geoip import (
        GeoLocation,         # dataclass: country (ISO-2), city, latitude, longitude
        lookup,              # (ip: str | None) -> GeoLocation | None  — fail-open
        extract_client_ip,   # (request: Request) -> str | None  — X-Forwarded-For aware
        refresh_database,    # () -> RefreshResult — used by cron + admin "refresh now"
        get_status,          # () -> StatusReport — for admin UI + /health
        GeoIPError,          # base of the error hierarchy (caught internally)
    )

Module boundary
---------------
This package depends on the rest of the cpmai backend through exactly ONE
abstraction: the ``SettingsProvider`` Protocol in ``protocols.py``. Every
other module (``lookup``, ``refresh``, ``cli``) is given a settings
provider — they never import from ``app.core.settings_store`` directly.

The cpmai-specific adapter lives in ``settings.py`` and is the only file
that touches the SystemSetting table. To lift this package into its own
service (its own FastAPI app, its own PyPI package), swap ``settings.py``
for an env-var, .ini-file, or HTTP-backed implementation and the rest of
the package keeps working unchanged.

See README.md in this directory for the full extraction guide.

Failure semantics
-----------------
* ``lookup()`` is FAIL-OPEN. Any error — missing mmdb, malformed IP,
  private/reserved IP, MaxMind DB doesn't recognize the IP — returns
  None. It NEVER raises to the caller. The caller's request path
  (lead capture, login) must not break because GeoIP misbehaves.
* ``refresh_database()`` raises ``GeoIPError`` subclasses on failure
  (bad credentials, network error, checksum mismatch). The cron script
  and admin endpoint catch these and surface the message — operators
  see a clear "what went wrong" line.
* ``get_status()`` never raises. It returns a status report even when
  the mmdb is absent, so the admin UI can render "no database installed".
"""
from app.services.geoip.domain import (
    GeoLocation,
    StatusReport,
    RefreshResult,
    GeoIPError,
    CredentialsError,
    DatabaseError,
    NetworkError,
)
from app.services.geoip.lookup import lookup, get_status
from app.services.geoip.refresh import refresh_database
from app.services.geoip.ip_extraction import extract_client_ip

__all__ = [
    "GeoLocation",
    "StatusReport",
    "RefreshResult",
    "GeoIPError",
    "CredentialsError",
    "DatabaseError",
    "NetworkError",
    "lookup",
    "get_status",
    "refresh_database",
    "extract_client_ip",
]
