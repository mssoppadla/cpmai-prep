"""FX orchestration — refresh + lookup + status.

This is the cpmai-specific layer that wires Frankfurter to our
settings store. The contract:

  refresh_rates()
      Called by cron daily. Fetches Frankfurter, applies the sanity
      cap (refuse >20% per-currency change on a single fetch — defends
      against API bugs / poisoned upstream data), writes results to
      ``pricing.fx_live_raw`` + ``pricing.fx_live_fetched_at``. Returns
      a RefreshResult summarising what happened.

  get_effective_rate(currency, ...)
      Hot-path lookup. Reads in priority order:
        1. ``pricing.fx_overrides[code]`` — admin lock (source=OVERRIDE)
        2. ``pricing.fx_live_raw[code]`` × (1 + markup/100) (source=LIVE)
        3. last-known live, age > stale_threshold (source=STALE)
        4. nothing → source=UNAVAILABLE (caller refuses to quote)
      NEVER raises. Used by PricingService on every quote.

  get_status()
      Snapshot for the admin /admin/pricing dashboard. Per-currency
      breakdown showing source, raw rate, effective rate, override,
      etc. Also feeds /health's fx_stale flag.

Settings consulted
------------------
  pricing.fx_live_raw          - dict[code, float], auto-managed by cron
  pricing.fx_live_fetched_at   - ISO-8601 str, auto-managed by cron
  pricing.fx_markup_percent    - admin-tunable (default 5)
  pricing.fx_overrides         - admin-tunable dict[code, float]
  pricing.supported_currencies - admin allow-list (empty = all auto-rate codes)

Sanity-cap details
------------------
Per-currency, if ``abs(new - old) / old > SANITY_CAP_PERCENT/100``,
that currency's old value is KEPT. The fetch still applies — partial
success — but the rejected codes are listed in RefreshResult.rejected_codes
so the cron log records them and the admin can investigate. If a
majority (>50%) of currencies trip the cap, the entire fetch is
rejected as ``SanityCapError`` (almost certainly a bad upstream
payload, not a real FX move).
"""
from __future__ import annotations
import time
from datetime import datetime, timezone
from typing import Optional

import structlog

from app.core.settings_store import settings_store
from app.services.fx.catalogue import (
    FRANKFURTER_SUPPORTED_CURRENCIES, symbol_for,
    RAZORPAY_SUPPORTED_CURRENCIES,
)
from app.services.fx.domain import (
    CurrencyStatus, EffectiveRate, FXError, RateSource, RefreshResult,
    SanityCapError, StatusReport,
)
from app.services.fx.frankfurter import fetch_rates_inr_base

log = structlog.get_logger("fx.service")


# Settings keys — constants so a typo at the call site is a NameError,
# not a silently-empty value.
class Keys:
    LIVE_RAW            = "pricing.fx_live_raw"
    LIVE_FETCHED_AT     = "pricing.fx_live_fetched_at"
    MARKUP_PERCENT      = "pricing.fx_markup_percent"
    OVERRIDES           = "pricing.fx_overrides"
    SUPPORTED           = "pricing.supported_currencies"


# Sanity cap: per-currency, reject a rate that moved more than this
# fraction since the last successful fetch. FX rarely moves >5% in a
# day; >20% is almost certainly a bad upstream payload.
SANITY_CAP_PERCENT = 20.0

# If a fetch trips the cap on more than this fraction of currencies,
# the WHOLE fetch is rejected. Defends against a Frankfurter outage
# returning garbage data on every currency.
WHOLESALE_REJECT_FRACTION = 0.5

# Stale threshold (days). Older than this and we serve the last-known
# rate with source=STALE so callers can warn.
STALE_THRESHOLD_DAYS = 7

# Default markup if the setting is unset / malformed. 5% covers
# Razorpay's ~3% international FX fee with ~2% headroom for FX drift
# between quote-time and capture-time.
DEFAULT_MARKUP_PERCENT = 5.0


# ============================================================ refresh

def refresh_rates() -> RefreshResult:
    """Cron-invoked: fetch live rates + apply sanity cap + persist.

    Idempotent. Multiple invocations within the same ECB publication
    cycle will all write the same data (Frankfurter returns the same
    rates until ECB publishes the next batch).
    """
    start = time.monotonic()
    log.info("fx.refresh_started")

    # Only fetch rates for currencies we actually offer (intersection
    # of Razorpay's set and Frankfurter's set). Asking Frankfurter for
    # codes it doesn't publish is a no-op anyway, but narrowing the
    # request keeps the network payload smaller.
    target_codes = sorted(RAZORPAY_SUPPORTED_CURRENCIES
                          & FRANKFURTER_SUPPORTED_CURRENCIES)
    inverted, ecb_date = fetch_rates_inr_base(codes=target_codes)

    # Sanity cap — compare new rates against previously stored live.
    previous = _read_live_raw()
    accepted: dict[str, float] = {}
    rejected: list[str] = []
    for code, new_rate in inverted.items():
        old_rate = previous.get(code)
        if old_rate is not None and old_rate > 0:
            change_pct = abs(new_rate - old_rate) / old_rate * 100.0
            if change_pct > SANITY_CAP_PERCENT:
                rejected.append(code)
                # Keep the OLD rate.
                accepted[code] = old_rate
                log.warning("fx.rate_rejected",
                            code=code, old=old_rate, new=new_rate,
                            change_pct=round(change_pct, 2),
                            cap_pct=SANITY_CAP_PERCENT)
                continue
        accepted[code] = new_rate

    # Wholesale-reject check: if more than half the currencies tripped
    # the cap, treat the whole fetch as suspicious and reject.
    if previous and rejected and \
            len(rejected) / len(inverted) > WHOLESALE_REJECT_FRACTION:
        raise SanityCapError(
            f"Sanity cap rejected {len(rejected)}/{len(inverted)} "
            f"rates (> {int(WHOLESALE_REJECT_FRACTION * 100)}%). "
            f"Likely a bad upstream payload — investigate before "
            f"forcing a refresh. Rejected codes: {', '.join(rejected)}."
        )

    # Persist. _write_settings takes a fake db param — settings_store
    # uses its own SessionLocal under the hood.
    fetched_at = datetime.now(timezone.utc)
    _write_live_raw(accepted, fetched_at)

    elapsed = time.monotonic() - start
    message = (
        f"Updated {len(accepted)} rates from Frankfurter "
        f"(ECB date: {ecb_date or 'unknown'}; markup {_markup_percent()}% "
        f"applied at quote-time)."
    )
    if rejected:
        message += f" Sanity cap kept {len(rejected)} rate(s) unchanged: " \
                   f"{', '.join(rejected)}."

    log.info("fx.refresh_completed",
             elapsed=elapsed, count=len(accepted),
             rejected=len(rejected), ecb_date=ecb_date)

    return RefreshResult(
        updated=True,
        fetched_at=fetched_at,
        rates_count=len(accepted),
        rejected_codes=rejected,
        elapsed_seconds=elapsed,
        message=message,
    )


# ===================================================== effective rate

def get_effective_rate(currency: str) -> EffectiveRate:
    """Hot-path lookup. NEVER raises.

    The PricingService consults this on every quote, so the contract is
    "always return something, even if it's UNAVAILABLE — caller decides
    what to render".
    """
    code = (currency or "").strip().upper()
    if not code:
        return EffectiveRate(
            currency="", inr_per_unit=1.0, source=RateSource.UNAVAILABLE)

    if code == "INR":
        return EffectiveRate(
            currency="INR", inr_per_unit=1.0, source=RateSource.INR)

    # Priority 1: admin override.
    overrides = _read_overrides()
    if code in overrides:
        return EffectiveRate(
            currency=code, inr_per_unit=overrides[code],
            source=RateSource.OVERRIDE,
            markup_percent=0.0,           # admin baked their own margin in
        )

    # Priority 2: live raw × (1 + markup).
    raw = _read_live_raw()
    fetched_at = _read_fetched_at()
    if code in raw and raw[code] > 0:
        markup = _markup_percent()
        marked_up = raw[code] * (1.0 + markup / 100.0)
        age_days = _age_days(fetched_at)
        source = (RateSource.STALE if age_days is not None
                  and age_days > STALE_THRESHOLD_DAYS else RateSource.LIVE)
        return EffectiveRate(
            currency=code,
            inr_per_unit=marked_up,
            source=source,
            markup_percent=markup,
            raw_inr_per_unit=raw[code],
            fetched_at=fetched_at,
            age_days=age_days,
        )

    # Priority 3: nothing.
    return EffectiveRate(
        currency=code, inr_per_unit=1.0, source=RateSource.UNAVAILABLE)


# ============================================================ status

def get_status() -> StatusReport:
    """Snapshot for /admin/pricing UI + /health fx_stale flag."""
    fetched_at = _read_fetched_at()
    age = _age_days(fetched_at)
    raw = _read_live_raw()
    overrides = _read_overrides()
    markup = _markup_percent()
    picker_filter = _picker_filter()

    rows: list[CurrencyStatus] = []

    # Universe = (live currencies we have rates for) ∪ (admin overrides) ∪ INR.
    universe = {"INR"} | set(raw.keys()) | set(overrides.keys())
    for code in sorted(universe):
        eff = get_effective_rate(code)
        in_picker = (not picker_filter) or (code in picker_filter)
        rows.append(CurrencyStatus(
            code=code, symbol=symbol_for(code),
            razorpay_supported=code in RAZORPAY_SUPPORTED_CURRENCIES,
            frankfurter_supported=code in FRANKFURTER_SUPPORTED_CURRENCIES,
            has_live_rate=code in raw,
            has_override=code in overrides,
            raw_inr_per_unit=raw.get(code),
            effective_inr_per_unit=(
                eff.inr_per_unit if eff.source != RateSource.UNAVAILABLE
                else None),
            source=eff.source,
            in_picker=in_picker,
        ))

    return StatusReport(
        last_fetched_at=fetched_at,
        age_days=age,
        stale=(age is not None and age > STALE_THRESHOLD_DAYS),
        markup_percent=markup,
        currencies=rows,
        last_refresh_message="",   # populated by callers that just ran a refresh
    )


# ======================================================== settings IO

def _read_live_raw() -> dict[str, float]:
    """Return the cached raw (pre-markup) live rates. Defensive against
    malformed settings (e.g. admin manually corrupted the JSON)."""
    v = settings_store.get(Keys.LIVE_RAW)
    if not isinstance(v, dict):
        return {}
    out: dict[str, float] = {}
    for code, rate in v.items():
        if not isinstance(code, str) or len(code.strip()) != 3:
            continue
        try:
            f = float(rate)
            if f > 0:
                out[code.strip().upper()] = f
        except (TypeError, ValueError):
            continue
    return out


def _read_overrides() -> dict[str, float]:
    v = settings_store.get(Keys.OVERRIDES)
    if not isinstance(v, dict):
        return {}
    out: dict[str, float] = {}
    for code, rate in v.items():
        if not isinstance(code, str) or len(code.strip()) != 3:
            continue
        try:
            f = float(rate)
            if f > 0:
                out[code.strip().upper()] = f
        except (TypeError, ValueError):
            continue
    return out


def _read_fetched_at() -> Optional[datetime]:
    v = settings_store.get(Keys.LIVE_FETCHED_AT)
    if not isinstance(v, str) or not v:
        return None
    # We store ISO-8601 with tz. Tolerate either timezone-aware or
    # naive (treat naive as UTC).
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _markup_percent() -> float:
    v = settings_store.get(Keys.MARKUP_PERCENT, DEFAULT_MARKUP_PERCENT)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return DEFAULT_MARKUP_PERCENT
    # Clamp to [0, 50]. The PATCH validator should reject out-of-range
    # values but defense-in-depth.
    return max(0.0, min(50.0, f))


def _picker_filter() -> set[str]:
    """Admin's optional allow-list. Empty set = no filter (show all
    currencies with rates)."""
    v = settings_store.get(Keys.SUPPORTED)
    if not isinstance(v, list):
        return set()
    out = set()
    for c in v:
        if isinstance(c, str) and len(c.strip()) == 3 and c.strip().isalpha():
            out.add(c.strip().upper())
    return out


def _age_days(fetched_at: Optional[datetime]) -> Optional[float]:
    if fetched_at is None:
        return None
    return (datetime.now(timezone.utc) - fetched_at).total_seconds() / 86400.0


def _write_live_raw(rates: dict[str, float], fetched_at: datetime) -> None:
    """Write the new live rates + timestamp directly to the settings
    table, then publish Redis invalidation so other workers pick up
    the change.

    Doesn't go through ``settings_store.set`` because that helper
    requires ``updated_by: int`` (a FK to ``users.id``), and the cron
    isn't a real user — we leave ``updated_by`` NULL.
    """
    from app.core.database import SessionLocal
    from app.core.redis import redis_client
    from app.core.settings_store import (
        CACHE_PREFIX, INVAL_CHANNEL, _local, _lock,
    )
    from app.models.system_setting import SystemSetting

    db = SessionLocal()
    try:
        for key, value in (
            (Keys.LIVE_RAW, rates),
            (Keys.LIVE_FETCHED_AT, fetched_at.isoformat()),
        ):
            row = db.get(SystemSetting, key)
            if row:
                row.value = value
                row.updated_by = None  # system-written, not by an admin
            else:
                db.add(SystemSetting(key=key, value=value, updated_by=None))
        db.commit()

        # Best-effort cache invalidation. If Redis is down we silently
        # tolerate — the local cache TTL (30s) will catch up eventually.
        for key in (Keys.LIVE_RAW, Keys.LIVE_FETCHED_AT):
            try:
                redis_client.delete(CACHE_PREFIX + key)
                redis_client.publish(INVAL_CHANNEL, key)
            except Exception:
                pass
            with _lock:
                _local.pop(key, None)
    finally:
        db.close()
