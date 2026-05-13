"""Protocols (structural interfaces) that decouple this package from
the rest of cpmai.

Why Protocols and not ABCs: structural typing means callers don't have
to inherit from us. A user of this package supplies any object whose
methods match — including a tiny test double, an env-var-backed shim,
or a future Redis-only implementation.

There are two protocols:

  1. ``SettingsProvider`` — read/write access to the few keys we need.
     The cpmai adapter in ``settings.py`` wraps ``settings_store``;
     a future extraction can wrap python-dotenv or Vault or whatever.

  2. ``GeoIPLookup`` — the lookup-engine interface. Defaults to
     ``MaxMindLookup`` (the only implementation today), but the indirection
     means tests can inject a fake without monkeypatching mmdb files, and
     a future swap to e.g. an IP2Location backend stays low-risk.

The keys in ``SettingsKeys`` are the contract between this package and
whatever settings backend is wired up. They are namespaced under
``geoip.`` so any settings table they share won't collide.
"""
from __future__ import annotations
from typing import Optional, Protocol, runtime_checkable

from app.services.geoip.domain import GeoLocation


class SettingsKeys:
    """The keys this package reads/writes. Constants instead of
    hardcoded strings so a typo at a call site is a NameError, not a
    silently-empty value."""
    MAXMIND_ACCOUNT_ID  = "geoip.maxmind_account_id"
    MAXMIND_LICENSE_KEY = "geoip.maxmind_license_key"
    REFRESH_ENABLED     = "geoip.refresh_enabled"
    REFRESH_SCHEDULE    = "geoip.refresh_schedule"
    TRUSTED_PROXY_COUNT = "geoip.trusted_proxy_count"

    ALL = (
        MAXMIND_ACCOUNT_ID,
        MAXMIND_LICENSE_KEY,
        REFRESH_ENABLED,
        REFRESH_SCHEDULE,
        TRUSTED_PROXY_COUNT,
    )


@runtime_checkable
class SettingsProvider(Protocol):
    """The single coupling point between this package and its host.

    Implementations MUST:
      * Return ``None`` (not raise) when a key is unset.
      * Never log the value of any key flagged ``is_secret=True``.
      * Be safe to call from multiple threads concurrently.
    """

    def get(self, key: str) -> Optional[str]: ...

    def get_bool(self, key: str, default: bool = False) -> bool: ...

    def get_int(self, key: str, default: int = 0) -> int: ...


@runtime_checkable
class GeoIPLookup(Protocol):
    """The lookup engine interface. Implementations must be fail-open —
    any internal error returns None, NEVER raises to the caller."""

    def lookup(self, ip: Optional[str]) -> Optional[GeoLocation]: ...
