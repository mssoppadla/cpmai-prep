"""Shared fixtures for the geoip unit-test suite.

We need a tiny but real mmdb file for the lookup tests. Building one
from scratch requires the ``maxminddb-writer`` package; to keep test
deps minimal we ship a 3-record synthetic mmdb in
``tests/unit/geoip/fixtures/`` (committed binary). The contents are
just enough to verify lookup behavior — three IPs covering happy path
+ private + unknown.

If the fixture is missing or unreadable, every lookup test should skip
(not fail) — so the suite still passes on developer machines that
haven't run ``git lfs pull`` or wherever we end up hosting the binary.

For the refresh tests we never use a real mmdb — httpx is mocked
end-to-end via ``respx`` (a dev dependency).
"""
from __future__ import annotations
import pathlib
from typing import Optional

import pytest

from app.services.geoip.protocols import SettingsProvider


FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"
SYNTHETIC_MMDB = FIXTURES_DIR / "test-City.mmdb"


@pytest.fixture
def synthetic_mmdb_path() -> pathlib.Path:
    """Path to a minimal-but-real mmdb file for lookup tests.

    Skips the test cleanly if the fixture isn't present — important on
    fresh checkouts before any ops bootstrap.
    """
    if not SYNTHETIC_MMDB.exists():
        pytest.skip(f"synthetic mmdb fixture not present at {SYNTHETIC_MMDB}; "
                    f"see tests/unit/geoip/fixtures/README.md for how to "
                    f"generate one.")
    return SYNTHETIC_MMDB


class InMemorySettings:
    """In-memory ``SettingsProvider`` for tests. Implements the Protocol
    structurally — no inheritance needed."""

    def __init__(self, store: Optional[dict] = None):
        self._store = dict(store or {})

    def get(self, key: str) -> Optional[str]:
        value = self._store.get(key)
        if value is None or value == "":
            return None
        return str(value)

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self._store.get(key)
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        return bool(value)

    def get_int(self, key: str, default: int = 0) -> int:
        value = self._store.get(key)
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def set(self, key: str, value):
        """Test-only setter — not part of the Protocol."""
        self._store[key] = value


@pytest.fixture
def settings() -> InMemorySettings:
    """A fresh in-memory settings provider per test. Tests that need
    populated credentials seed this fixture before exercising code."""
    return InMemorySettings()


# Sanity: the InMemorySettings shape matches the Protocol.
def test_in_memory_settings_matches_protocol():
    assert isinstance(InMemorySettings(), SettingsProvider)
