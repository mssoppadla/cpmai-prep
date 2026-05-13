"""Foreign-exchange package — live rates + admin overrides + markup.

Public API (the only symbols callers outside this package should use):

    from app.services.fx import (
        RAZORPAY_SUPPORTED_CURRENCIES,     # set of ISO codes Razorpay International can charge
        FRANKFURTER_SUPPORTED_CURRENCIES,  # set of ISO codes Frankfurter publishes
        symbol_for,                         # (code) -> "$" / "€" / etc.
        refresh_rates,                      # () -> RefreshResult — pulls live + writes settings
        get_effective_rate,                 # (code, base_paise) -> EffectiveRate (with breakdown)
        get_status,                         # () -> StatusReport for /admin/pricing
        EffectiveRate, RefreshResult, StatusReport,   # dataclasses
        FXError, NetworkError, SanityCapError,        # error hierarchy
    )

Module boundary
---------------
Like the geoip package, this is designed to be extractable. The only
cpmai-specific dependency is the settings_store adapter — everything
else is pure logic + the Frankfurter HTTP client. To lift this into
another app: swap the settings adapter, keep the rest.

Failure semantics
-----------------
* ``refresh_rates()`` raises ``FXError`` subclasses on failure. The CLI
  + admin endpoint catch these and surface clear operator messages.
* ``get_effective_rate()`` NEVER raises — returns an EffectiveRate
  whose ``source`` field tells the caller what data it actually used
  (live / override / stale / inr / unavailable).
"""
from app.services.fx.catalogue import (
    RAZORPAY_SUPPORTED_CURRENCIES,
    FRANKFURTER_SUPPORTED_CURRENCIES,
    symbol_for,
)
from app.services.fx.domain import (
    EffectiveRate, RefreshResult, StatusReport, RateSource,
    FXError, NetworkError, SanityCapError, FXDataError,
)
from app.services.fx.service import (
    refresh_rates, get_effective_rate, get_status,
)

__all__ = [
    "RAZORPAY_SUPPORTED_CURRENCIES",
    "FRANKFURTER_SUPPORTED_CURRENCIES",
    "symbol_for",
    "EffectiveRate", "RefreshResult", "StatusReport", "RateSource",
    "FXError", "NetworkError", "SanityCapError", "FXDataError",
    "refresh_rates", "get_effective_rate", "get_status",
]
