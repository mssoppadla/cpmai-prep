"""Download a fresh GeoLite2-City database from MaxMind.

Workflow
--------
1. Read account_id + license_key from the SettingsProvider.
2. HEAD MaxMind to check the latest etag/last-modified vs. our local
   db_date. If they match, return ``updated=False`` (no download).
3. GET the tar.gz + the matching .sha256 file.
4. Verify sha256 of the tar.gz against the published checksum.
5. Extract the .mmdb out of the tarball into a .tmp file.
6. Validate the .tmp file with ``maxminddb.open_database()`` — proves
   it's not a corrupted/truncated file.
7. Atomically rename .tmp → final path.
8. Invalidate the in-process lookup cache.
9. Return a RefreshResult with timing + sizes.

Safety properties
-----------------
* **Atomic install**: the final ``os.replace()`` is the only step that
  changes the file lookups see. Either the new file is fully in place
  or it isn't — there is no window where a partial file is visible.
* **Concurrency**: this function is NOT safe to call concurrently —
  multiple threads would clobber each other in the .tmp directory.
  The VPS refresh script uses ``flock``; the admin endpoint is rate-
  limited so manual collisions are unlikely.
* **Secrets**: the license key is never logged. Error messages refer
  to it by key NAME, not value. The HTTP basic-auth credentials are
  built from the settings provider at call time and discarded after.
* **Fail-loud**: unlike ``lookup()``, ``refresh_database()`` raises
  ``GeoIPError`` subclasses on failure. The caller (CLI / admin
  endpoint) translates these to operator-friendly messages.

Notes
-----
* MaxMind serves the file under a query-string-auth URL OR via HTTP
  basic auth. We use basic auth — it doesn't expose the license_key in
  proxy access logs the way a query-string would.
* We download to ``/srv/cpmai/geoip/`` by convention. Override via the
  ``destination`` arg for tests.
"""
from __future__ import annotations
import hashlib
import os
import shutil
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Optional

import httpx
import structlog

from app.services.geoip.domain import (
    CredentialsError, DatabaseError, NetworkError, RefreshResult,
)
from app.services.geoip.lookup import DEFAULT_DB_PATH, invalidate_default
from app.services.geoip.protocols import SettingsKeys, SettingsProvider
from app.services.geoip.settings import default_provider

log = structlog.get_logger("geoip.refresh")


MAXMIND_DOWNLOAD_URL = "https://download.maxmind.com/app/geoip_download"
EDITION_ID = "GeoLite2-City"
DEFAULT_TIMEOUT = 60.0   # one minute should be plenty for a 30MB file
USER_AGENT = "cpmai-geoip/1.0 (https://cpmaiexamprep.com)"


def refresh_database(
    *,
    destination: Path = DEFAULT_DB_PATH,
    settings: SettingsProvider = default_provider,
    timeout: float = DEFAULT_TIMEOUT,
) -> RefreshResult:
    """Download (if needed) and install the GeoLite2-City database.

    Args:
        destination: Final path for the .mmdb file. Parent directory
            must exist and be writable. Defaults to
            ``/srv/cpmai/geoip/GeoLite2-City.mmdb``.
        settings: Settings provider with the MaxMind credentials.
        timeout: Per-HTTP-request timeout (seconds).

    Raises:
        CredentialsError: account_id or license_key empty, or MaxMind
            rejects them with 401.
        NetworkError: DNS, connection, or non-200/304 status.
        DatabaseError: checksum mismatch, tarball malformed, or extracted
            mmdb fails to open.

    Returns:
        RefreshResult.updated=True if a new file was installed.
        RefreshResult.updated=False if MaxMind reports we already have
        the latest (HTTP 304). Both are SUCCESS cases.
    """
    start = time.monotonic()

    account_id = settings.get(SettingsKeys.MAXMIND_ACCOUNT_ID)
    license_key = settings.get(SettingsKeys.MAXMIND_LICENSE_KEY)
    if not account_id or not license_key:
        raise CredentialsError(
            "MaxMind credentials not configured. Set "
            f"{SettingsKeys.MAXMIND_ACCOUNT_ID} and "
            f"{SettingsKeys.MAXMIND_LICENSE_KEY} via /admin/settings."
        )

    destination = Path(destination)
    if not destination.parent.exists():
        # Caller is expected to have run install_geoip.sh which sets
        # up the directory. Failing loudly here surfaces that miss
        # immediately rather than during the atomic rename.
        raise DatabaseError(
            f"Destination directory does not exist: {destination.parent}. "
            f"Run scripts/vps/install_geoip.sh first."
        )

    auth = (account_id, license_key)
    headers = {"User-Agent": USER_AGENT}

    # 1. Conditional GET via If-Modified-Since. MaxMind returns 304 if
    #    we already have the latest. We use the destination's mtime as
    #    our "what we have" marker — same idea as a browser cache, no
    #    separate state to track.
    if destination.exists():
        try:
            since = destination.stat().st_mtime
            # HTTP date format for If-Modified-Since
            import email.utils
            headers["If-Modified-Since"] = email.utils.formatdate(
                since, usegmt=True)
        except OSError:
            pass

    params = {"edition_id": EDITION_ID, "suffix": "tar.gz"}

    log.info("geoip.refresh_started", destination=str(destination))

    with tempfile.TemporaryDirectory(prefix="geoip_refresh_") as tmpdir:
        tmpdir_path = Path(tmpdir)
        tarball_path = tmpdir_path / "db.tar.gz"
        sha256_path = tmpdir_path / "db.sha256"

        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                # 1a. Download the tarball.
                resp = client.get(MAXMIND_DOWNLOAD_URL, params=params,
                                  auth=auth, headers=headers)
                if resp.status_code == 304:
                    elapsed = time.monotonic() - start
                    size = destination.stat().st_size if destination.exists() else 0
                    log.info("geoip.refresh_not_modified",
                             elapsed=elapsed, size=size)
                    return RefreshResult(
                        updated=False,
                        database_size_bytes=size,
                        elapsed_seconds=elapsed,
                        message="No update available (304 Not Modified).",
                    )
                if resp.status_code == 401:
                    raise CredentialsError(
                        "MaxMind rejected the license key. Verify the "
                        f"value of {SettingsKeys.MAXMIND_LICENSE_KEY} in "
                        f"/admin/settings (or rotate it at maxmind.com)."
                    )
                if resp.status_code != 200:
                    raise NetworkError(
                        f"MaxMind returned HTTP {resp.status_code} when "
                        f"downloading {EDITION_ID}."
                    )
                tarball_path.write_bytes(resp.content)
                bytes_downloaded = len(resp.content)

                # 1b. Download the published checksum.
                sha_params = {"edition_id": EDITION_ID,
                              "suffix": "tar.gz.sha256"}
                sha_resp = client.get(MAXMIND_DOWNLOAD_URL,
                                      params=sha_params,
                                      auth=auth, headers={"User-Agent": USER_AGENT})
                if sha_resp.status_code != 200:
                    raise NetworkError(
                        f"MaxMind returned HTTP {sha_resp.status_code} "
                        "when downloading the sha256 checksum."
                    )
                # MaxMind's .sha256 format: "<hex>  GeoLite2-City_*.tar.gz\n"
                expected_sha = sha_resp.text.split()[0].lower().strip()
                sha256_path.write_text(sha_resp.text)
        except httpx.HTTPError as exc:
            # DNS, timeout, connect-refused — anything httpx considers
            # a transport error.
            raise NetworkError(
                f"MaxMind download failed: {type(exc).__name__}: {exc}"
            ) from exc

        # 2. Verify checksum.
        actual_sha = hashlib.sha256(tarball_path.read_bytes()).hexdigest().lower()
        if actual_sha != expected_sha:
            raise DatabaseError(
                f"Checksum mismatch on GeoLite2-City download. "
                f"expected={expected_sha[:16]}… got={actual_sha[:16]}…"
            )

        # 3. Extract the .mmdb file out of the tarball.
        extracted_mmdb = _extract_mmdb(tarball_path, tmpdir_path)

        # 4. Smoke-test the file by opening it. Catches truncated or
        #    corrupt extractions before we replace the live file.
        try:
            import maxminddb
            with maxminddb.open_database(str(extracted_mmdb)) as test_reader:
                # Trivial lookup just to exercise the index.
                test_reader.get("8.8.8.8")
        except Exception as exc:
            raise DatabaseError(
                f"Extracted mmdb failed to open: {type(exc).__name__}: {exc}"
            ) from exc

        # 5. Atomic install. os.replace is atomic on the same filesystem
        #    on POSIX. Stage the file next to the destination so the
        #    rename is same-FS guaranteed.
        staging_path = destination.with_suffix(destination.suffix + ".staging")
        shutil.copy2(extracted_mmdb, staging_path)
        os.replace(staging_path, destination)

        # 6. Determine the YYYYMMDD date in the tarball's internal path
        #    (e.g. "GeoLite2-City_20260512/GeoLite2-City.mmdb"). Useful
        #    for the admin UI "DB version" line.
        database_date = _parse_db_date_from_tarball(tarball_path)

    # 7. Drop the in-process reader cache so the next lookup picks up
    #    the new file even on filesystems with second-precision mtimes.
    invalidate_default()

    elapsed = time.monotonic() - start
    final_size = destination.stat().st_size
    log.info("geoip.refresh_completed",
             elapsed=elapsed,
             bytes_downloaded=bytes_downloaded,
             database_size=final_size,
             database_date=database_date)

    return RefreshResult(
        updated=True,
        database_date=database_date,
        database_size_bytes=final_size,
        bytes_downloaded=bytes_downloaded,
        elapsed_seconds=elapsed,
        message=f"Installed GeoLite2-City {database_date or '(date unknown)'}.",
    )


def _extract_mmdb(tarball_path: Path, into: Path) -> Path:
    """Pull the .mmdb file out of MaxMind's tarball into ``into``.

    The tarball layout is::

        GeoLite2-City_YYYYMMDD/
          ├── GeoLite2-City.mmdb
          ├── COPYRIGHT.txt
          └── LICENSE.txt

    We don't care which subdir — just find the first member ending in
    ``.mmdb`` and extract it.

    Defends against tarball path-traversal: rejects any member whose
    extracted path would escape ``into``.
    """
    try:
        with tarfile.open(tarball_path, mode="r:gz") as tar:
            for member in tar.getmembers():
                if not member.isfile() or not member.name.endswith(".mmdb"):
                    continue
                # Path-traversal guard.
                resolved = (into / member.name).resolve()
                if not str(resolved).startswith(str(into.resolve())):
                    raise DatabaseError(
                        f"Tarball member escapes destination: {member.name}"
                    )
                tar.extract(member, path=into)
                return resolved
    except tarfile.TarError as exc:
        raise DatabaseError(f"Tarball malformed: {exc}") from exc
    raise DatabaseError("No .mmdb member found in the GeoLite2-City tarball.")


def _parse_db_date_from_tarball(tarball_path: Path) -> Optional[str]:
    """Return the YYYYMMDD slug embedded in the tarball's top-level
    directory name, or None if we can't find it."""
    try:
        with tarfile.open(tarball_path, mode="r:gz") as tar:
            for member in tar.getmembers():
                # member.name is like "GeoLite2-City_20260512/..."
                head = member.name.split("/", 1)[0]
                if "_" in head:
                    parts = head.rsplit("_", 1)
                    if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 8:
                        return parts[1]
    except tarfile.TarError:
        return None
    return None
