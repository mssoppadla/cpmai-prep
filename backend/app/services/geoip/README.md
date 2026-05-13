# geoip — IP → country/city enrichment

A self-contained Python package for resolving IPs to geographic
locations using MaxMind's GeoLite2-City database. Designed to be
extractable from cpmai with minimal effort.

## Public API

```python
from app.services.geoip import (
    GeoLocation,         # dataclass: country, city, latitude, longitude
    lookup,              # (ip) -> GeoLocation | None  — fail-open
    extract_client_ip,   # (Request) -> str | None
    refresh_database,    # () -> RefreshResult
    get_status,          # () -> StatusReport
    GeoIPError,          # base of error hierarchy
)
```

Typical request-path usage:

```python
ip = extract_client_ip(request)
geo = lookup(ip)
if geo:
    lead.country = geo.country
    lead.city = geo.city
```

## Module layout

| File | Purpose |
|---|---|
| `__init__.py` | Public API exports |
| `domain.py` | `GeoLocation`, `StatusReport`, `RefreshResult`, error classes |
| `protocols.py` | `SettingsProvider` and `GeoIPLookup` Protocols — the seam |
| `lookup.py` | `MaxMindLookup` — mmap-backed reader with mtime hot-reload |
| `refresh.py` | `refresh_database()` — download, verify, atomic install |
| `settings.py` | **cpmai-specific** adapter wrapping `settings_store` |
| `ip_extraction.py` | `X-Forwarded-For` parsing with trusted-proxy discipline |
| `cli.py` | argparse-based CLI for cron + ops |
| `__main__.py` | Makes `python -m app.services.geoip` work |

## Coupling story

The entire package depends on the rest of cpmai through **one** file:
`settings.py`. Every other module receives a `SettingsProvider` as a
constructor / function argument.

```
┌─────────────────────────────────────────┐
│ app.services.geoip.*                    │
│   ┌──────────┐  ┌──────────┐  ┌──────┐  │
│   │ lookup   │  │ refresh  │  │ cli  │  │
│   └────┬─────┘  └────┬─────┘  └──┬───┘  │
│        └───────┬─────┴───────────┘      │
│                ▼                        │
│        ┌────────────────┐               │
│        │ SettingsProvider│ (Protocol)   │
│        └───────┬────────┘               │
└────────────────┼────────────────────────┘
                 │
        ┌────────▼────────────┐
        │ settings.py:         │
        │ CpmaiSettingsProvider│ ──→ app.core.settings_store
        └──────────────────────┘
```

## Extracting this package

To use this package in a non-cpmai application:

1. **Copy the package directory.** Drop `app/services/geoip/` into the
   target codebase (or `pip install` it from a private index after
   packaging — left as future work).

2. **Replace `settings.py` with your own SettingsProvider.** Any class
   with `get`, `get_bool`, `get_int` methods matching the Protocol will
   work. Common shapes:

   * **Env-var-backed** (zero dependencies):
     ```python
     import os
     class EnvSettingsProvider:
         def get(self, key): return os.environ.get(key.upper().replace(".", "_")) or None
         def get_bool(self, key, default=False):
             v = self.get(key);  return v.lower() in ("true","1","yes") if v else default
         def get_int(self, key, default=0):
             v = self.get(key);  return int(v) if v and v.isdigit() else default
     ```

   * **File-backed** (`config.ini`): wrap `configparser`.

   * **HTTP-backed**: fetch from a config service on the network.

3. **Wire the provider into the module-level singletons.** The simplest
   approach is a module-load-time hook in your app:

   ```python
   from app.services.geoip import lookup as _geoip_module
   from app.services.geoip.lookup import MaxMindLookup
   _geoip_module._default_lookup = MaxMindLookup(settings=my_provider)
   ```

   Or call `lookup` / `refresh_database` with `settings=` explicitly.

4. **Run the install + cron scripts** (in `scripts/vps/`) for ops
   integration, or use the CLI:

   ```
   python -m app.services.geoip refresh
   ```

5. **Install the runtime dependencies:**
   * `maxminddb` (>= 2.0) — the mmdb reader
   * `httpx` (>= 0.24) — the download client
   * `structlog` (any) — used for log lines (replace with stdlib
     logging if you prefer; the surface is minimal)

## Settings keys

| Key | Type | Secret | Default | Purpose |
|---|---|---|---|---|
| `geoip.maxmind_account_id` | int (as string) | no | — | MaxMind account ID for download auth |
| `geoip.maxmind_license_key` | string | **yes** | — | MaxMind license key |
| `geoip.refresh_enabled` | bool | no | `true` | Set false to halt cron refreshes |
| `geoip.trusted_proxy_count` | int | no | `1` | How many `X-Forwarded-For` hops are ours |

## Failure model

* `lookup()` is **fail-open**. Any error (no mmdb, bad IP, MaxMind miss,
  reader crash) returns `None`. Never raises.
* `refresh_database()` is **fail-loud**. Raises `CredentialsError`,
  `NetworkError`, or `DatabaseError` for distinct failure modes. CLI
  exit codes map 1:1 (1/2/3).
* `get_status()` is **fail-safe**. Returns a report even if no mmdb
  exists; `database_present` distinguishes.

## Security notes

* The license key is `is_secret=True` in the settings table. The
  `/admin/settings` GET endpoint masks it as `"••••last4"`. PATCH still
  accepts plaintext.
* `CpmaiSettingsProvider.__repr__()` is overridden to avoid leaking
  even the presence of values into logs.
* The refresh function uses HTTP basic auth, not a query-string
  credential — this keeps the key out of proxy access logs.
* Errors include the SETTING KEY NAME (so operators can rotate it),
  never the value.

## Performance

* mmap-backed reader. After first open, lookups are sub-microsecond.
* mtime hot-reload: no app restart needed after a refresh. The reader
  is reopened on the next request after mtime changes.
* The reader is held per-process. With 4 uvicorn workers, that's 4
  mmap'd copies — each lazy-paged, so RSS doesn't multiply.

## Testing

The package's tests live in `backend/tests/unit/geoip/` and use a
tiny synthetic mmdb fixture (built by `maxminddb-writer` or copied from
[maxmind/MaxMind-DB-Reader-python](https://github.com/maxmind/MaxMind-DB-Reader-python)'s
test data). No live MaxMind calls in unit tests.

For an end-to-end test against the real service, run:

```
python -m app.services.geoip refresh
python -m app.services.geoip lookup 8.8.8.8
```

## Operations

* **Initial install**: `scripts/vps/install_geoip.sh` (runs once per
  VPS — creates the directory, sets perms, does the first download).
* **Scheduled refresh**: `scripts/vps/geoip_refresh.sh` (cron-invoked
  twice weekly — Wednesdays + Saturdays at 04:17 UTC — `flock`-guarded,
  logs to `/var/log/cpmai/geoip_refresh.log`). The schedule is aligned
  with MaxMind's release cadence (Tuesdays + Fridays, ~14–22 UTC), so
  each run is 6–14 hours after a release. ~8 invocations/month, ~2 of
  which actually download (~30 MB each); the rest return 304 Not
  Modified via conditional-GET (If-Modified-Since). Total bandwidth:
  ~60 MB/month.
* **Manual refresh**: `/admin/geoip` page → "Refresh now" button (rate
  limited to 3 per hour per admin).
* **Status check**: `/health` endpoint includes `geoip.database_present`
  and `geoip.database_age_days`.
* **Stale-data alarm**: if the mmdb file is older than 35 days,
  `get_status()` flags `database_stale=True` and the `/admin/geoip`
  page shows a warning. With the twice-weekly schedule, hitting 35 days
  means at least 8 missed refreshes — unambiguously a problem to
  investigate.
