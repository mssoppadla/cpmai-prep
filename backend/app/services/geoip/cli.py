"""Command-line interface for the geoip package.

Four subcommands:

    python -m app.services.geoip refresh [--only-if-scheduled]
        Run a refresh (download + install). Used by the recurring cron
        (every minute on the VPS; the --only-if-scheduled flag gates
        the actual work against ``geoip.refresh_schedule`` — see
        scripts/vps/install_geoip_cron.sh + scheduler.py).

        With --only-if-scheduled (the cron path):
          * Reads geoip.refresh_schedule from settings.
          * If the current minute doesn't match → exit 0 silently.
          * If it matches → proceed with the refresh.
        Without --only-if-scheduled (manual / "refresh now" path):
          * Unconditionally runs.

        Exit codes:
          0 = success (whether updated=True, =False, or skipped-by-schedule)
          1 = credentials error
          2 = network error
          3 = database/integrity error
          4 = misuse (bad args)

    python -m app.services.geoip status
        Print the StatusReport as JSON. Used by ops dashboards.
        Always exits 0 (status reporting itself doesn't fail).

    python -m app.services.geoip lookup <ip>
        Look up a single IP. Useful for "is this prod working?" smoke
        tests from the VPS. Exits 0 on success, 1 if no record found.

    python -m app.services.geoip next-runs [--count N]
        Print the next N times the configured refresh schedule will
        fire. Used by the admin UI's preview AND by ops "did I set the
        schedule right?" sanity checks. Always exits 0.

Design notes
------------
* No third-party CLI framework (Click/Typer) — argparse keeps the
  dependency footprint of this package small. Argparse is in stdlib.
* The CLI uses ``default_provider`` (CpmaiSettingsProvider). This means
  running the CLI on the VPS reads from the live system_settings table —
  the same key the admin UI writes to. No env-var shadowing, no
  separate config file.
* Output is plain text by default and JSON via ``--json``. The cron
  script uses plain text (more readable in mail); ops dashboards use
  JSON.
* Exit codes are stable — the cron wrapper inspects them.
"""
from __future__ import annotations
import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from typing import Optional

from app.services.geoip import (
    CredentialsError, DatabaseError, NetworkError,
    lookup as do_lookup,
    get_status,
    refresh_database,
)
from app.services.geoip.protocols import SettingsKeys
from app.services.geoip.scheduler import (
    DEFAULT_SCHEDULE, is_scheduled_now, next_run_times,
)
from app.services.geoip.settings import default_provider


EXIT_OK = 0
EXIT_CREDENTIALS = 1
EXIT_NETWORK = 2
EXIT_DATABASE = 3
EXIT_MISUSE = 4
EXIT_NOT_FOUND = 1   # for `lookup` only — distinct from refresh exits


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="app.services.geoip",
        description="GeoIP enrichment CLI for cpmai. Talks to MaxMind, "
                    "manages the local GeoLite2-City.mmdb, looks up IPs.",
    )
    parser.add_argument("--json", action="store_true",
                        help="Emit output as JSON (one object per command).")
    sub = parser.add_subparsers(dest="command", required=True)

    p_refresh = sub.add_parser("refresh",
        help="Download + install latest GeoLite2-City.")
    # The cron wrapper passes --only-if-scheduled so a minute-tick that
    # doesn't match the admin-configured schedule exits silently. Manual
    # runs (the admin "Refresh now" button + interactive ops) omit the
    # flag and always proceed.
    p_refresh.add_argument(
        "--only-if-scheduled", action="store_true",
        help="Run only if the current minute matches geoip.refresh_schedule. "
             "Used by the every-minute cron; exits 0 silently when not "
             "scheduled. Manual runs should omit this flag.")

    sub.add_parser("status", help="Print operational status snapshot.")

    p_lookup = sub.add_parser("lookup", help="Resolve a single IP.")
    p_lookup.add_argument("ip", help="IPv4 or IPv6 address to look up.")

    p_next = sub.add_parser("next-runs",
        help="Print the next N times the configured schedule will fire.")
    p_next.add_argument("--count", type=int, default=5,
        help="How many upcoming run times to show. Default 5.")

    args = parser.parse_args(argv)

    if args.command == "refresh":
        return _cmd_refresh(
            emit_json=args.json,
            only_if_scheduled=args.only_if_scheduled,
        )
    if args.command == "status":
        return _cmd_status(emit_json=args.json)
    if args.command == "lookup":
        return _cmd_lookup(args.ip, emit_json=args.json)
    if args.command == "next-runs":
        return _cmd_next_runs(count=args.count, emit_json=args.json)
    return EXIT_MISUSE


def _cmd_refresh(*, emit_json: bool, only_if_scheduled: bool = False) -> int:
    if only_if_scheduled:
        # Gate the refresh on the admin-configured schedule. This is the
        # cron-hot-path: invoked every minute. Most invocations exit 0
        # here without doing any work (no settings read needed beyond
        # one key, no MaxMind call, no file I/O).
        expr = default_provider.get(SettingsKeys.REFRESH_SCHEDULE) or DEFAULT_SCHEDULE
        if not is_scheduled_now(expr):
            # Silent exit — DO NOT print anything to stdout/stderr.
            # The cron wrapper logs every line we emit; spamming "not
            # scheduled" on 1438 of 1440 daily ticks would drown the
            # 2 real refresh entries.
            return EXIT_OK
        # We matched a scheduled minute. Refresh-disabled kill switch
        # also gates the actual work — we check it here, AFTER deciding
        # the schedule matched, so the operator sees "schedule matched
        # but kill switch is on" in the cron log when relevant.
        if not default_provider.get_bool(SettingsKeys.REFRESH_ENABLED, True):
            print("Schedule matched but geoip.refresh_enabled=false — "
                  "skipping. Re-enable in /admin/settings to resume.")
            return EXIT_OK

    try:
        result = refresh_database()
    except CredentialsError as exc:
        _emit_error("credentials", str(exc), emit_json)
        return EXIT_CREDENTIALS
    except NetworkError as exc:
        _emit_error("network", str(exc), emit_json)
        return EXIT_NETWORK
    except DatabaseError as exc:
        _emit_error("database", str(exc), emit_json)
        return EXIT_DATABASE
    if emit_json:
        print(json.dumps(asdict(result), default=_json_default))
    else:
        print(result.message)
        print(f"  updated:            {result.updated}")
        print(f"  database_date:      {result.database_date or 'n/a'}")
        print(f"  database_size:      {_human_bytes(result.database_size_bytes)}")
        print(f"  bytes_downloaded:   {_human_bytes(result.bytes_downloaded)}")
        print(f"  elapsed:            {result.elapsed_seconds:.2f}s")
    return EXIT_OK


def _cmd_status(*, emit_json: bool) -> int:
    report = get_status()
    if emit_json:
        print(json.dumps(asdict(report), default=_json_default))
    else:
        print(f"database_path:         {report.database_path}")
        print(f"database_present:      {report.database_present}")
        if report.database_present:
            print(f"database_size:         {_human_bytes(report.database_size_bytes or 0)}")
            print(f"database_mtime:        {report.database_mtime}")
            print(f"database_age_days:     {report.database_age_days}")
            print(f"database_stale:        {report.database_stale}")
        print(f"credentials_configured: {report.credentials_configured}")
        print(f"last_lookup_count:     {report.last_lookup_count}")
    return EXIT_OK


def _cmd_lookup(ip: str, *, emit_json: bool) -> int:
    geo = do_lookup(ip)
    if geo is None:
        if emit_json:
            print(json.dumps({"ip": ip, "found": False}))
        else:
            print(f"No record for {ip} (private IP, no mmdb, or not in DB).")
        return EXIT_NOT_FOUND
    if emit_json:
        print(json.dumps({"ip": ip, "found": True, **asdict(geo)}))
    else:
        print(f"ip:        {ip}")
        print(f"country:   {geo.country or '?'}")
        print(f"city:      {geo.city or '?'}")
        print(f"latitude:  {geo.latitude if geo.latitude is not None else '?'}")
        print(f"longitude: {geo.longitude if geo.longitude is not None else '?'}")
    return EXIT_OK


def _cmd_next_runs(*, count: int, emit_json: bool) -> int:
    """Print the next N upcoming runs of the configured schedule."""
    expr = default_provider.get(SettingsKeys.REFRESH_SCHEDULE) or DEFAULT_SCHEDULE
    runs = next_run_times(expr, count=max(1, min(count, 50)))
    if emit_json:
        print(json.dumps({
            "schedule": expr,
            "next_runs": [r.isoformat() for r in runs],
        }))
    else:
        print(f"schedule: {expr}")
        if not runs:
            print("  (no upcoming runs — schedule may be invalid)")
        for run in runs:
            print(f"  {run.isoformat()}")
    return EXIT_OK


def _emit_error(kind: str, message: str, emit_json: bool) -> None:
    if emit_json:
        json.dump({"error": kind, "message": message}, sys.stderr)
        sys.stderr.write("\n")
    else:
        sys.stderr.write(f"[{kind}] {message}\n")


def _human_bytes(n: int) -> str:
    """Format bytes for human display in CLI output."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KiB"
    return f"{n / (1024 * 1024):.1f} MiB"


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


if __name__ == "__main__":
    sys.exit(main())
