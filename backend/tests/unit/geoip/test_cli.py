"""CLI tests — argparse routing + exit codes.

We patch the underlying functions (lookup, refresh_database, get_status)
so this suite exercises CLI plumbing only, not the lookup/refresh logic
(which are covered by their own modules' tests).

Exit codes are part of the cron contract — see the wrapper script in
scripts/vps/geoip_refresh.sh. Breaking these codes silently would mean
cron-failure alerts go missing.
"""
from __future__ import annotations
from unittest.mock import patch

import pytest

from app.services.geoip import RefreshResult, StatusReport, GeoLocation
from app.services.geoip.cli import (
    main, EXIT_OK, EXIT_CREDENTIALS, EXIT_NETWORK, EXIT_DATABASE,
    EXIT_NOT_FOUND,
)
from app.services.geoip.domain import (
    CredentialsError, NetworkError, DatabaseError,
)


# -------------------------------------------------- refresh exit codes

def test_cli_refresh_success_exits_zero(capsys):
    fake = RefreshResult(updated=True, database_date="20260512",
                         database_size_bytes=12345,
                         bytes_downloaded=12345,
                         elapsed_seconds=1.2,
                         message="Installed.")
    with patch("app.services.geoip.cli.refresh_database", return_value=fake):
        rc = main(["refresh"])
    assert rc == EXIT_OK
    out = capsys.readouterr().out
    assert "Installed." in out


def test_cli_refresh_credentials_error_exits_one(capsys):
    with patch("app.services.geoip.cli.refresh_database",
               side_effect=CredentialsError("creds bad")):
        rc = main(["refresh"])
    assert rc == EXIT_CREDENTIALS
    err = capsys.readouterr().err
    assert "creds bad" in err


def test_cli_refresh_network_error_exits_two(capsys):
    with patch("app.services.geoip.cli.refresh_database",
               side_effect=NetworkError("net bad")):
        rc = main(["refresh"])
    assert rc == EXIT_NETWORK


def test_cli_refresh_database_error_exits_three(capsys):
    with patch("app.services.geoip.cli.refresh_database",
               side_effect=DatabaseError("db bad")):
        rc = main(["refresh"])
    assert rc == EXIT_DATABASE


def test_cli_refresh_304_is_success(capsys):
    """updated=False (304 Not Modified) is a SUCCESS — exit 0, not an error."""
    fake = RefreshResult(updated=False, database_size_bytes=12345,
                         bytes_downloaded=0,
                         elapsed_seconds=0.5,
                         message="No update available (304).")
    with patch("app.services.geoip.cli.refresh_database", return_value=fake):
        rc = main(["refresh"])
    assert rc == EXIT_OK


# --------------------------------------------------- json output shape

def test_cli_refresh_json_output(capsys):
    import json as _json
    fake = RefreshResult(updated=True, database_date="20260512",
                         database_size_bytes=10,
                         bytes_downloaded=10,
                         elapsed_seconds=0.1, message="ok")
    with patch("app.services.geoip.cli.refresh_database", return_value=fake):
        rc = main(["--json", "refresh"])
    assert rc == EXIT_OK
    payload = _json.loads(capsys.readouterr().out.strip())
    assert payload["updated"] is True
    assert payload["database_date"] == "20260512"


# ------------------------------------------------------------ status

def test_cli_status_always_exits_zero(capsys):
    fake = StatusReport(database_present=False, database_path="/x")
    with patch("app.services.geoip.cli.get_status", return_value=fake):
        rc = main(["status"])
    assert rc == EXIT_OK
    out = capsys.readouterr().out
    assert "/x" in out


def test_cli_status_json(capsys):
    import json as _json
    fake = StatusReport(database_present=True,
                        database_path="/p", database_size_bytes=100)
    with patch("app.services.geoip.cli.get_status", return_value=fake):
        rc = main(["--json", "status"])
    assert rc == EXIT_OK
    payload = _json.loads(capsys.readouterr().out.strip())
    assert payload["database_present"] is True
    assert payload["database_path"] == "/p"


# ------------------------------------------------------------- lookup

def test_cli_lookup_known_ip(capsys):
    fake = GeoLocation(country="IN", city="Bengaluru")
    with patch("app.services.geoip.cli.do_lookup", return_value=fake):
        rc = main(["lookup", "203.0.113.1"])
    assert rc == EXIT_OK
    out = capsys.readouterr().out
    assert "IN" in out and "Bengaluru" in out


def test_cli_lookup_unknown_ip(capsys):
    with patch("app.services.geoip.cli.do_lookup", return_value=None):
        rc = main(["lookup", "10.0.0.1"])
    assert rc == EXIT_NOT_FOUND
    out = capsys.readouterr().out
    assert "no record" in out.lower()


def test_cli_lookup_json(capsys):
    import json as _json
    fake = GeoLocation(country="IN", city="Bengaluru",
                       latitude=12.97, longitude=77.59)
    with patch("app.services.geoip.cli.do_lookup", return_value=fake):
        rc = main(["--json", "lookup", "203.0.113.1"])
    assert rc == EXIT_OK
    payload = _json.loads(capsys.readouterr().out.strip())
    assert payload["found"] is True
    assert payload["country"] == "IN"


# --------------------------------------------------------- misuse

def test_cli_missing_subcommand_exits_nonzero(capsys):
    """argparse should exit 2 (usage) when no subcommand is given."""
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code != 0
