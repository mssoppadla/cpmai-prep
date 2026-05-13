"""Lookup tests — exercise the MaxMindLookup against the synthetic
fixture mmdb. Tests skip cleanly if the fixture isn't present.

We test:

  * Happy path: known IPv4 → expected GeoLocation
  * Happy path: known IPv6 → expected GeoLocation
  * Country-only record: city is None, country is set
  * Unknown IP: returns None (fail-open)
  * Private IP: returns None without even touching the DB
  * Bad input: returns None
  * mmdb file missing: returns None (no crash)
  * mtime hot-reload: write a new file, next lookup picks it up
  * status report shape when DB present
"""
from __future__ import annotations
import os
import shutil
import time
from datetime import datetime, timedelta, timezone

from app.services.geoip.domain import GeoLocation
from app.services.geoip.lookup import MaxMindLookup, STALE_THRESHOLD_DAYS


# ---------------------------------------------------------- happy path

def test_lookup_known_ipv4(synthetic_mmdb_path, settings):
    """1.1.1.1 → IN / Bengaluru, per the fixture."""
    lookup = MaxMindLookup(db_path=synthetic_mmdb_path, settings=settings)
    geo = lookup.lookup("1.1.1.1")
    assert isinstance(geo, GeoLocation)
    assert geo.country == "IN"
    assert geo.city == "Bengaluru"


def test_lookup_known_ipv6(synthetic_mmdb_path, settings):
    """2606:4700::1 → SG / Singapore, per the fixture."""
    lookup = MaxMindLookup(db_path=synthetic_mmdb_path, settings=settings)
    geo = lookup.lookup("2606:4700::1")
    assert isinstance(geo, GeoLocation)
    assert geo.country == "SG"
    assert geo.city == "Singapore"


def test_lookup_country_only_record(synthetic_mmdb_path, settings):
    """8.8.8.8 → AE with no city. We must return country=AE and
    city=None — not crash, not blank out the country."""
    lookup = MaxMindLookup(db_path=synthetic_mmdb_path, settings=settings)
    geo = lookup.lookup("8.8.8.8")
    assert geo is not None
    assert geo.country == "AE"
    assert geo.city is None


# ----------------------------------------------------------- fail-open

def test_lookup_unknown_ip_returns_none(synthetic_mmdb_path, settings):
    """An IP not in the fixture returns None — NOT an empty GeoLocation.

    9.9.9.9 (Quad9 DNS) is a publicly routable address that we deliberately
    DID NOT seed in the fixture. We can't use RFC 5737 doc IPs here because
    Python 3.12+ classifies them as ``is_private`` and the lookup short-
    circuits before consulting the DB — which would still return None,
    but for the wrong reason.
    """
    lookup = MaxMindLookup(db_path=synthetic_mmdb_path, settings=settings)
    assert lookup.lookup("9.9.9.9") is None


def test_lookup_private_ip_returns_none(settings, tmp_path):
    """Private/RFC1918/loopback IPs short-circuit to None without
    touching the DB. We even use a missing DB path to prove the
    short-circuit happens before any I/O."""
    lookup = MaxMindLookup(db_path=tmp_path / "does-not-exist.mmdb",
                           settings=settings)
    for private_ip in ("127.0.0.1", "10.0.0.1", "192.168.1.1",
                       "172.16.0.1", "::1", "fe80::1"):
        assert lookup.lookup(private_ip) is None, (
            f"{private_ip} should short-circuit to None")


def test_lookup_empty_or_none_input(settings, tmp_path):
    """Defensive: empty string and None both return None safely."""
    lookup = MaxMindLookup(db_path=tmp_path / "x.mmdb", settings=settings)
    assert lookup.lookup(None) is None
    assert lookup.lookup("") is None


def test_lookup_invalid_ip_format(settings, tmp_path):
    """Garbage input returns None — no exception leaks."""
    lookup = MaxMindLookup(db_path=tmp_path / "x.mmdb", settings=settings)
    assert lookup.lookup("not.an.ip") is None
    assert lookup.lookup("999.999.999.999") is None


def test_lookup_missing_database(settings, tmp_path):
    """No file → None. The hot path must not blow up because the
    mmdb hasn't been installed yet."""
    lookup = MaxMindLookup(db_path=tmp_path / "missing.mmdb",
                           settings=settings)
    assert lookup.lookup("1.1.1.1") is None


# ----------------------------------------------------------- hot reload

def test_lookup_reopens_after_mtime_change(synthetic_mmdb_path, settings,
                                           tmp_path):
    """The whole point of mtime-based hot reload: a refresh writes a
    new file in place; the next lookup picks it up automatically.

    We simulate by: opening with one path, doing a lookup, then
    copying-over the same file (which updates mtime) and verifying
    that a subsequent lookup still succeeds with no manual invalidate."""
    target = tmp_path / "test-City.mmdb"
    shutil.copy(synthetic_mmdb_path, target)

    lookup = MaxMindLookup(db_path=target, settings=settings)
    assert lookup.lookup("1.1.1.1") is not None
    first_mtime = lookup._reader_mtime  # type: ignore[attr-defined]

    # Force mtime forward by at least 1 second (some filesystems have
    # second-resolution mtimes).
    time.sleep(1.1)
    shutil.copy(synthetic_mmdb_path, target)

    # Subsequent lookup must succeed AND the reader must have re-opened.
    assert lookup.lookup("1.1.1.1") is not None
    new_mtime = lookup._reader_mtime  # type: ignore[attr-defined]
    assert new_mtime != first_mtime, (
        "Reader did not re-open after file mtime changed.")


def test_invalidate_drops_reader(synthetic_mmdb_path, settings):
    """invalidate() is the refresh path's belt-and-suspenders: even on
    coarse-mtime filesystems, the next lookup must reopen."""
    lookup = MaxMindLookup(db_path=synthetic_mmdb_path, settings=settings)
    assert lookup.lookup("1.1.1.1") is not None
    assert lookup._reader is not None  # type: ignore[attr-defined]

    lookup.invalidate()
    assert lookup._reader is None  # type: ignore[attr-defined]

    # Still works after invalidate — next lookup re-opens.
    assert lookup.lookup("1.1.1.1") is not None


# ------------------------------------------------------------- status

def test_status_when_database_present(synthetic_mmdb_path, settings):
    lookup = MaxMindLookup(db_path=synthetic_mmdb_path, settings=settings)
    # Trigger one lookup so the counter is non-zero.
    lookup.lookup("1.1.1.1")
    report = lookup.get_status()
    assert report.database_present is True
    assert report.database_size_bytes is not None and report.database_size_bytes > 0
    assert report.database_age_days is not None
    assert report.last_lookup_count >= 1
    assert isinstance(report.database_mtime, datetime)


def test_status_when_database_missing(settings, tmp_path):
    lookup = MaxMindLookup(db_path=tmp_path / "absent.mmdb",
                           settings=settings)
    report = lookup.get_status()
    assert report.database_present is False
    assert report.database_size_bytes is None
    assert report.database_age_days is None
    assert report.database_stale is False  # safe default


def test_status_stale_threshold(synthetic_mmdb_path, settings, tmp_path):
    """If we artificially backdate the file, get_status reports stale=True."""
    target = tmp_path / "stale.mmdb"
    shutil.copy(synthetic_mmdb_path, target)
    # Backdate by STALE_THRESHOLD_DAYS + 5 days.
    old = time.time() - (STALE_THRESHOLD_DAYS + 5) * 86400
    os.utime(target, (old, old))
    lookup = MaxMindLookup(db_path=target, settings=settings)
    report = lookup.get_status()
    assert report.database_present is True
    assert report.database_stale is True
    assert report.database_age_days >= STALE_THRESHOLD_DAYS


def test_status_credentials_configured_signal(settings, tmp_path):
    """The flag flips True only when BOTH account_id and license_key
    are set in the settings provider."""
    from app.services.geoip.protocols import SettingsKeys
    lookup = MaxMindLookup(db_path=tmp_path / "x.mmdb", settings=settings)

    # Neither set.
    assert lookup.get_status().credentials_configured is False

    # Just one set.
    settings.set(SettingsKeys.MAXMIND_ACCOUNT_ID, "1234567")
    assert lookup.get_status().credentials_configured is False

    # Both set.
    settings.set(SettingsKeys.MAXMIND_LICENSE_KEY, "fake_key")
    assert lookup.get_status().credentials_configured is True
