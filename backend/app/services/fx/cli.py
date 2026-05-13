"""Command-line interface for the FX package.

Three subcommands:

    python -m app.services.fx refresh
        Pull live rates from Frankfurter, apply the sanity cap, persist
        to settings. Used by the daily cron. Exit codes:
          0 = success
          1 = network error (Frankfurter unreachable / non-200)
          2 = data error (Frankfurter response malformed)
          3 = sanity cap rejected the whole fetch (>50% bad rates)
          4 = misuse (bad args)

    python -m app.services.fx status
        Print the StatusReport as JSON. Always exits 0.

    python -m app.services.fx rates [--currency CODE]
        Print the current effective rates table. Used to verify what
        the cron last wrote. Always exits 0.

Output is JSON when --json is passed, otherwise plain text suitable
for cron mail. Stable exit codes are part of the cron wrapper's
contract — see scripts/vps/fx_refresh.sh.
"""
from __future__ import annotations
import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from typing import Optional

from app.services.fx import (
    FXError, NetworkError, SanityCapError, FXDataError,
    refresh_rates, get_effective_rate, get_status,
)


EXIT_OK = 0
EXIT_NETWORK = 1
EXIT_DATA = 2
EXIT_SANITY = 3
EXIT_MISUSE = 4


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="app.services.fx",
        description="FX refresh CLI for cpmai. Pulls Frankfurter rates, "
                    "applies markup at quote-time, and manages the "
                    "rate-cache settings.",
    )
    parser.add_argument("--json", action="store_true",
                        help="Emit output as JSON (one object per command).")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("refresh", help="Pull live rates + persist to settings.")
    sub.add_parser("status", help="Print the FX status snapshot.")
    p_rates = sub.add_parser("rates", help="Print the effective rates table.")
    p_rates.add_argument("--currency", help="Limit output to one currency.")

    args = parser.parse_args(argv)

    if args.command == "refresh":
        return _cmd_refresh(emit_json=args.json)
    if args.command == "status":
        return _cmd_status(emit_json=args.json)
    if args.command == "rates":
        return _cmd_rates(currency=args.currency, emit_json=args.json)
    return EXIT_MISUSE


def _cmd_refresh(*, emit_json: bool) -> int:
    try:
        result = refresh_rates()
    except NetworkError as exc:
        _emit_error("network", str(exc), emit_json)
        return EXIT_NETWORK
    except FXDataError as exc:
        _emit_error("data", str(exc), emit_json)
        return EXIT_DATA
    except SanityCapError as exc:
        _emit_error("sanity", str(exc), emit_json)
        return EXIT_SANITY
    except FXError as exc:
        _emit_error("fx", str(exc), emit_json)
        return EXIT_NETWORK
    if emit_json:
        print(json.dumps(asdict(result), default=_json_default))
    else:
        print(result.message)
        print(f"  fetched_at:        {result.fetched_at}")
        print(f"  rates_count:       {result.rates_count}")
        print(f"  rejected_codes:    {result.rejected_codes or '(none)'}")
        print(f"  elapsed:           {result.elapsed_seconds:.2f}s")
    return EXIT_OK


def _cmd_status(*, emit_json: bool) -> int:
    report = get_status()
    if emit_json:
        # asdict on a nested dataclass works; the CurrencyStatus's
        # source enum needs default= str so json serialises it.
        print(json.dumps(asdict(report), default=_json_default))
    else:
        print(f"last_fetched_at:     {report.last_fetched_at}")
        print(f"age_days:            {report.age_days}")
        print(f"stale:               {report.stale}")
        print(f"markup_percent:      {report.markup_percent}")
        print(f"currencies ({len(report.currencies)}):")
        for cur in report.currencies:
            mark = "★" if cur.in_picker else " "
            print(f"  {mark} {cur.code:3s} src={cur.source.value:11s} "
                  f"rate={cur.effective_inr_per_unit}")
    return EXIT_OK


def _cmd_rates(*, currency: Optional[str], emit_json: bool) -> int:
    if currency:
        rate = get_effective_rate(currency)
        if emit_json:
            print(json.dumps(asdict(rate), default=_json_default))
        else:
            print(f"{rate.currency}: "
                  f"{rate.inr_per_unit} INR per 1 unit  "
                  f"(source={rate.source.value}, "
                  f"markup={rate.markup_percent}%, "
                  f"raw={rate.raw_inr_per_unit})")
        return EXIT_OK
    # No currency filter — dump everything from status.
    return _cmd_status(emit_json=emit_json)


def _emit_error(kind: str, message: str, emit_json: bool) -> None:
    if emit_json:
        json.dump({"error": kind, "message": message}, sys.stderr)
        sys.stderr.write("\n")
    else:
        sys.stderr.write(f"[{kind}] {message}\n")


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):  # Enum
        return value.value
    return str(value)


if __name__ == "__main__":
    sys.exit(main())
