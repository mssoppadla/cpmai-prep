"""Refresh-flow tests. httpx is fully mocked via respx so the suite
never makes a real network call.

We test:

  * Credentials unset → CredentialsError (no HTTP call)
  * 401 from MaxMind → CredentialsError
  * 304 from MaxMind → updated=False, returns success
  * 200 + valid tarball + matching sha256 → updated=True, file installed
  * 200 + bad sha256 → DatabaseError
  * Network error → NetworkError
  * Tarball missing .mmdb → DatabaseError
  * Path-traversal in tarball → DatabaseError

Tests construct synthetic tarballs in tmp_path so we control every
byte. We DON'T need the synthetic mmdb fixture because we mock the
``maxminddb.open_database`` smoke-test call.
"""
from __future__ import annotations
import gzip
import hashlib
import io
import tarfile
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import respx

from app.services.geoip.domain import (
    CredentialsError, DatabaseError, NetworkError,
)
from app.services.geoip.protocols import SettingsKeys
from app.services.geoip.refresh import (
    refresh_database, MAXMIND_DOWNLOAD_URL,
)


def _build_synthetic_tarball(*,
                             dir_name: str = "GeoLite2-City_20260512",
                             mmdb_bytes: bytes = b"FAKE-MMDB-CONTENT",
                             include_mmdb: bool = True,
                             escape_path: bool = False) -> bytes:
    """Build an in-memory tar.gz that looks like MaxMind's shape.

    Args:
        dir_name: top-level directory inside the tarball.
        mmdb_bytes: contents of the .mmdb file (just needs to be non-empty).
        include_mmdb: if False, the tarball has no .mmdb member (DatabaseError).
        escape_path: if True, the .mmdb path tries to escape via '../'
            (the path-traversal defense test).
    """
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as tar:
        if include_mmdb:
            inner_path = (f"../../etc/passwd-pwn.mmdb" if escape_path
                          else f"{dir_name}/GeoLite2-City.mmdb")
            info = tarfile.TarInfo(name=inner_path)
            info.size = len(mmdb_bytes)
            tar.addfile(info, io.BytesIO(mmdb_bytes))
        # Always include the LICENSE.txt so the structure looks real.
        license_text = b"Synthetic test fixture."
        info = tarfile.TarInfo(name=f"{dir_name}/LICENSE.txt")
        info.size = len(license_text)
        tar.addfile(info, io.BytesIO(license_text))
    return raw.getvalue()


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def configured(settings, tmp_path):
    """Settings with valid-looking credentials + a writable destination dir."""
    settings.set(SettingsKeys.MAXMIND_ACCOUNT_ID, "1234567")
    settings.set(SettingsKeys.MAXMIND_LICENSE_KEY, "fake_license_key_xyz")
    dest = tmp_path / "geoip"
    dest.mkdir()
    return settings, dest / "GeoLite2-City.mmdb"


# ----------------------------------------------------------- credentials

def test_refresh_no_credentials_raises_credentials_error(settings, tmp_path):
    """Empty settings → CredentialsError BEFORE any HTTP call."""
    dest = tmp_path / "GeoLite2-City.mmdb"
    (tmp_path).mkdir(exist_ok=True)
    with pytest.raises(CredentialsError) as exc:
        refresh_database(destination=dest, settings=settings)
    assert "credentials not configured" in str(exc.value).lower()


@respx.mock
def test_refresh_401_from_maxmind_raises_credentials_error(configured):
    settings, dest = configured
    respx.get(MAXMIND_DOWNLOAD_URL).mock(
        return_value=httpx.Response(401, text="unauthorized"))
    with pytest.raises(CredentialsError) as exc:
        refresh_database(destination=dest, settings=settings)
    assert "rejected" in str(exc.value).lower()


# --------------------------------------------------------------- 304 path

@respx.mock
def test_refresh_304_returns_not_updated(configured):
    """MaxMind says we already have the latest. Returns success with updated=False."""
    settings, dest = configured
    # Create an existing file so the conditional-GET path triggers If-Modified-Since.
    dest.write_bytes(b"existing")
    respx.get(MAXMIND_DOWNLOAD_URL).mock(
        return_value=httpx.Response(304))
    result = refresh_database(destination=dest, settings=settings)
    assert result.updated is False
    assert result.bytes_downloaded == 0
    assert "304" in result.message or "not modified" in result.message.lower()


# --------------------------------------------------------- happy path 200

@respx.mock
def test_refresh_happy_path_200_installs_file(configured):
    settings, dest = configured

    # Mock maxminddb.open_database so it always succeeds (the file we
    # extract is fake bytes — a real mmdb reader would reject it).
    tarball = _build_synthetic_tarball()
    sha = _sha256_hex(tarball)

    # respx matches in declaration order; we set up two routes that
    # differ by suffix param.
    def _route(request):
        if request.url.params.get("suffix") == "tar.gz.sha256":
            return httpx.Response(200, text=f"{sha}  GeoLite2-City_20260512.tar.gz\n")
        return httpx.Response(200, content=tarball,
                              headers={"content-type": "application/gzip"})
    respx.get(MAXMIND_DOWNLOAD_URL).mock(side_effect=_route)

    with patch("maxminddb.open_database") as mock_open:
        mock_open.return_value.__enter__.return_value.get.return_value = None
        result = refresh_database(destination=dest, settings=settings)

    assert result.updated is True
    assert result.database_date == "20260512"
    assert result.bytes_downloaded == len(tarball)
    assert dest.exists()
    assert dest.read_bytes() == b"FAKE-MMDB-CONTENT"


# ---------------------------------------------------------- bad checksum

@respx.mock
def test_refresh_sha256_mismatch_raises_database_error(configured):
    settings, dest = configured
    tarball = _build_synthetic_tarball()

    def _route(request):
        if request.url.params.get("suffix") == "tar.gz.sha256":
            # Wrong sha — pretend the file is something else.
            return httpx.Response(200, text="deadbeef" * 8 + "  whatever.tar.gz\n")
        return httpx.Response(200, content=tarball)
    respx.get(MAXMIND_DOWNLOAD_URL).mock(side_effect=_route)

    with pytest.raises(DatabaseError) as exc:
        refresh_database(destination=dest, settings=settings)
    assert "checksum" in str(exc.value).lower()
    # The original file (if any) is untouched on failure.
    assert not dest.exists()


# ---------------------------------------------------------- network error

@respx.mock
def test_refresh_network_error_raises_network_error(configured):
    settings, dest = configured
    respx.get(MAXMIND_DOWNLOAD_URL).mock(
        side_effect=httpx.ConnectError("nope"))
    with pytest.raises(NetworkError) as exc:
        refresh_database(destination=dest, settings=settings)
    assert "ConnectError" in str(exc.value) or "failed" in str(exc.value).lower()


@respx.mock
def test_refresh_unexpected_status_raises_network_error(configured):
    """500 from MaxMind isn't a credentials issue, it's transport-level
    (their CDN is having a moment). NetworkError signal so ops can retry."""
    settings, dest = configured
    respx.get(MAXMIND_DOWNLOAD_URL).mock(
        return_value=httpx.Response(503, text="upstream"))
    with pytest.raises(NetworkError):
        refresh_database(destination=dest, settings=settings)


# --------------------------------------------------------- bad tarball

@respx.mock
def test_refresh_tarball_missing_mmdb_raises_database_error(configured):
    settings, dest = configured
    tarball = _build_synthetic_tarball(include_mmdb=False)
    sha = _sha256_hex(tarball)

    def _route(request):
        if request.url.params.get("suffix") == "tar.gz.sha256":
            return httpx.Response(200, text=f"{sha}  x.tar.gz\n")
        return httpx.Response(200, content=tarball)
    respx.get(MAXMIND_DOWNLOAD_URL).mock(side_effect=_route)

    with pytest.raises(DatabaseError) as exc:
        refresh_database(destination=dest, settings=settings)
    assert "no .mmdb member" in str(exc.value).lower()


@respx.mock
def test_refresh_tarball_path_traversal_blocked(configured):
    """A tarball with '../../etc/...' must NOT extract outside the
    tmp dir. This is the same class of bug as 'zip slip'."""
    settings, dest = configured
    tarball = _build_synthetic_tarball(escape_path=True)
    sha = _sha256_hex(tarball)

    def _route(request):
        if request.url.params.get("suffix") == "tar.gz.sha256":
            return httpx.Response(200, text=f"{sha}  x.tar.gz\n")
        return httpx.Response(200, content=tarball)
    respx.get(MAXMIND_DOWNLOAD_URL).mock(side_effect=_route)

    with pytest.raises(DatabaseError) as exc:
        refresh_database(destination=dest, settings=settings)
    assert "escape" in str(exc.value).lower() or "no .mmdb" in str(exc.value).lower()


# ---------------------------------------------------------- missing dest

def test_refresh_missing_destination_dir_raises_database_error(settings, tmp_path):
    """If the destination's parent dir doesn't exist (operator forgot
    to run install_geoip.sh), surface a clear message."""
    settings.set(SettingsKeys.MAXMIND_ACCOUNT_ID, "1")
    settings.set(SettingsKeys.MAXMIND_LICENSE_KEY, "k")
    dest = tmp_path / "nonexistent-dir" / "GeoLite2-City.mmdb"
    with pytest.raises(DatabaseError) as exc:
        refresh_database(destination=dest, settings=settings)
    assert "does not exist" in str(exc.value).lower()
    assert "install_geoip" in str(exc.value).lower()
