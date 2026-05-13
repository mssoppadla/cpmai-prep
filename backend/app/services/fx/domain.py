"""Domain types for the FX package.

Dataclasses + error hierarchy. Kept Pydantic-free so the package stays
extractable (matches the geoip package's convention from PR-A).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class RateSource(str, Enum):
    """Where did the effective FX rate we returned ACTUALLY come from?

    The frontend uses this to decide whether to surface a "live FX"
    footnote vs. a "manual rate" tooltip vs. a "rate is stale" warning.
    """
    INR             = "inr"           # base currency, rate is always 1
    LIVE            = "live"          # ECB-mid-market × (1 + markup)
    OVERRIDE        = "override"      # admin-set value in pricing.fx_overrides
    STALE           = "stale"         # last-known live rate, > stale-threshold old
    UNAVAILABLE     = "unavailable"   # no rate at all — caller should refuse to quote


@dataclass(frozen=True)
class EffectiveRate:
    """The rate the caller should use, with full provenance.

    ``inr_per_unit`` is the multiplier: ``foreign_units = inr_paise / 100 / inr_per_unit``.
    For INR itself, ``inr_per_unit = 1.0``.

    ``markup_percent`` is what the live-rate cron already added on top
    of the raw ECB value (5% by default). Reported back so the quote
    can break it out as a transparent "international processing fee"
    line item rather than burying it in the rate.

    For non-LIVE sources the markup is reported as 0 (the override
    rate IS the effective rate — admin already factored their margin
    in if they wanted to).
    """
    currency: str
    inr_per_unit: float
    source: RateSource
    markup_percent: float = 0.0
    # Raw mid-market rate (pre-markup) when source=LIVE. None otherwise.
    raw_inr_per_unit: Optional[float] = None
    # When the data was last fetched (LIVE/STALE only).
    fetched_at: Optional[datetime] = None
    # Days since fetched (LIVE/STALE only).
    age_days: Optional[float] = None


@dataclass
class RefreshResult:
    """Outcome of ``refresh_rates()`` — what the cron just did."""
    updated: bool
    fetched_at: Optional[datetime] = None
    rates_count: int = 0
    # Codes where the new rate differed >20% from previous fetch.
    # These get REJECTED (kept the old value) as a sanity guard
    # against Frankfurter API bugs / data poisoning.
    rejected_codes: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    message: str = ""


@dataclass
class CurrencyStatus:
    """Per-currency snapshot for the admin /admin/pricing UI."""
    code: str
    symbol: str
    razorpay_supported: bool   # in RAZORPAY_SUPPORTED_CURRENCIES
    frankfurter_supported: bool   # in FRANKFURTER_SUPPORTED_CURRENCIES
    has_live_rate: bool
    has_override: bool
    raw_inr_per_unit: Optional[float]   # live mid-market (pre-markup)
    effective_inr_per_unit: Optional[float]  # what get_effective_rate would use
    source: RateSource
    in_picker: bool   # appears in /pricing dropdown (passes the supported-currencies filter)


@dataclass
class StatusReport:
    """Snapshot for /admin/pricing dashboard + /health flag."""
    last_fetched_at: Optional[datetime] = None
    age_days: Optional[float] = None
    stale: bool = False                     # age > stale_threshold
    markup_percent: float = 0.0
    currencies: list[CurrencyStatus] = field(default_factory=list)
    last_refresh_message: str = ""          # human-readable last cron status


# ===================================================== error hierarchy

class FXError(Exception):
    """Base for errors raised by the explicit-failure paths
    (``refresh_rates`` + the CLI). ``get_effective_rate`` does NOT
    raise — it returns ``UNAVAILABLE`` on any miss."""


class NetworkError(FXError):
    """Frankfurter request failed (DNS, timeout, non-2xx).

    Operator action: check VPS connectivity to api.frankfurter.dev.
    """


class SanityCapError(FXError):
    """The sanity cap rejected enough rates that we refused to apply
    the fetch at all (>50% of currencies moved more than the cap).
    Almost certainly a bad upstream payload — investigate before
    flipping the kill switch.
    """


class FXDataError(FXError):
    """Frankfurter returned 200 but the body didn't match the expected
    shape (missing ``rates`` field, malformed JSON, etc.). Distinguish
    from NetworkError because the operator action differs — file a
    bug rather than checking the network."""
