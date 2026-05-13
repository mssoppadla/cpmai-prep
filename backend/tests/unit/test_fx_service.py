"""FX service tests — Frankfurter mock + sanity cap + lookup priority.

Coverage:

  fetch / parse path  (frankfurter.py)
    * happy path: 200 with inverted rates
    * non-200 → NetworkError
    * malformed body → FXDataError
    * network exception → NetworkError

  refresh path  (service.refresh_rates)
    * persists to settings + sets fetched_at
    * sanity cap: per-currency >20% move is REJECTED (kept old value)
    * sanity cap: >50% rejection → SanityCapError raised
    * first fetch (no previous data) skips sanity cap

  lookup path  (service.get_effective_rate)
    * INR → source=INR, rate=1
    * non-INR + live → source=LIVE, rate = raw × (1 + markup)
    * non-INR + override → source=OVERRIDE, rate = override (no markup)
    * non-INR + stale → source=STALE
    * non-INR + nothing → source=UNAVAILABLE
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import pytest
import respx

from app.services.fx import (
    EffectiveRate, FXDataError, NetworkError, RateSource, SanityCapError,
    get_effective_rate, refresh_rates,
)
from app.services.fx.frankfurter import FRANKFURTER_URL


# Frankfurter publishes "X per 1 INR" — we want to feed it rates that
# invert to clean numbers for assertion. 0.012 USD per INR → 83.33 INR
# per USD. 0.011 EUR per INR → 90.91 INR per EUR.
FRESH_RESPONSE = {
    "amount": 1.0,
    "base": "INR",
    "date": "2026-05-14",
    "rates": {"USD": 0.012, "EUR": 0.011, "GBP": 0.0095},
}


# ============================================================ fetch

@respx.mock
def test_fetch_inverts_rates_correctly(db):
    """Frankfurter publishes USD-per-INR; we invert to INR-per-USD."""
    respx.get(FRANKFURTER_URL).mock(
        return_value=httpx.Response(200, json=FRESH_RESPONSE))
    from app.services.fx.frankfurter import fetch_rates_inr_base
    rates, date = fetch_rates_inr_base()
    # 1 / 0.012 ≈ 83.33
    assert abs(rates["USD"] - 83.333333) < 0.01
    assert abs(rates["EUR"] - 90.90909) < 0.01
    assert date == "2026-05-14"


@respx.mock
def test_fetch_400_raises_network_error(db):
    """Non-200 surfaces as NetworkError with the status code in the
    message (so the operator sees what MaxMind/Frankfurter said)."""
    respx.get(FRANKFURTER_URL).mock(
        return_value=httpx.Response(500, text="server error"))
    from app.services.fx.frankfurter import fetch_rates_inr_base
    with pytest.raises(NetworkError) as exc:
        fetch_rates_inr_base()
    assert "500" in str(exc.value)


@respx.mock
def test_fetch_malformed_body_raises_data_error(db):
    """Body missing 'rates' → FXDataError, distinct from a network
    issue so the operator action differs (file a bug, not poke the network)."""
    respx.get(FRANKFURTER_URL).mock(
        return_value=httpx.Response(200, json={"amount": 1.0}))
    from app.services.fx.frankfurter import fetch_rates_inr_base
    with pytest.raises(FXDataError):
        fetch_rates_inr_base()


@respx.mock
def test_fetch_network_exception_raises_network_error(db):
    """httpx.ConnectError → NetworkError."""
    respx.get(FRANKFURTER_URL).mock(
        side_effect=httpx.ConnectError("nope"))
    from app.services.fx.frankfurter import fetch_rates_inr_base
    with pytest.raises(NetworkError):
        fetch_rates_inr_base()


# ============================================================ refresh

@respx.mock
def test_refresh_persists_rates_and_timestamp(db, monkeypatch):
    """Happy path: pull, sanity-cap, write to settings.

    Mocks ``_write_live_raw`` so we don't need a real Postgres session
    (the unit test environment runs against SQLite). The settings
    round-trip is exercised in the integration tests.
    """
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: default)   # no previous data

    written: dict = {}
    monkeypatch.setattr("app.services.fx.service._write_live_raw",
                        lambda r, f: written.update({"rates": r, "fetched_at": f}))

    respx.get(FRANKFURTER_URL).mock(
        return_value=httpx.Response(200, json=FRESH_RESPONSE))
    result = refresh_rates()
    assert result.updated is True
    assert result.rates_count == 3
    assert result.rejected_codes == []
    assert result.fetched_at is not None

    # The write got the inverted rates.
    assert "USD" in written["rates"]
    assert abs(written["rates"]["USD"] - 83.333) < 0.1
    assert written["fetched_at"] is not None


@respx.mock
def test_refresh_sanity_cap_keeps_old_value_on_big_move(db, monkeypatch):
    """Pre-load the settings with USD=80, then have Frankfurter return
    a USD rate that would invert to 200 (way more than 20% jump).
    The new rate gets REJECTED; the old 80 survives. EUR moves only
    a little so it's accepted."""
    # Pre-load previous live rates via direct settings_store mock.
    # The cron uses _read_live_raw which reads from settings_store.
    from app.core import settings_store as ss_module
    stored: dict = {
        "pricing.fx_live_raw": {"USD": 80.0, "EUR": 90.0},
    }

    # Return the default sentinel for any unknown key WITHOUT touching
    # the real settings_store (which would try to open Postgres).
    def fake_get(self, k, default=None):
        if k in stored:
            return stored[k]
        return default
    monkeypatch.setattr(ss_module.SettingsStore, "get", fake_get)

    # Frankfurter returns: USD with rate 0.005 → 200 INR/USD (BIG move
    # from 80 → cap rejects). EUR with 0.011 → 90.91 (small move from
    # 90, accepted).
    respx.get(FRANKFURTER_URL).mock(
        return_value=httpx.Response(200, json={
            "amount": 1.0, "base": "INR", "date": "2026-05-14",
            "rates": {"USD": 0.005, "EUR": 0.011},
        }))

    # Stub the write so we can inspect what got persisted (and avoid
    # actually touching the DB — we're mocking settings reads above).
    written: dict = {}

    def fake_write(rates, fetched_at):
        written["rates"] = rates
        written["fetched_at"] = fetched_at
    monkeypatch.setattr("app.services.fx.service._write_live_raw", fake_write)

    result = refresh_rates()
    assert "USD" in result.rejected_codes
    assert "EUR" not in result.rejected_codes
    # Written rates: USD kept at 80 (rejected); EUR updated to ~90.91.
    assert written["rates"]["USD"] == 80.0
    assert abs(written["rates"]["EUR"] - 90.909) < 0.1


@respx.mock
def test_refresh_sanity_cap_wholesale_rejection(db, monkeypatch):
    """If >50% of currencies trip the cap, refuse the WHOLE fetch as
    suspicious (almost certainly a bad upstream payload, not real
    FX). Raises SanityCapError so the operator investigates."""
    from app.core import settings_store as ss_module
    stored = {"pricing.fx_live_raw": {
        "USD": 80.0, "EUR": 90.0, "GBP": 100.0}}

    def fake_get(self, k, default=None):
        if k in stored:
            return stored[k]
        return default
    monkeypatch.setattr(ss_module.SettingsStore, "get", fake_get)

    # All three currencies moved >20% — implausible.
    respx.get(FRANKFURTER_URL).mock(
        return_value=httpx.Response(200, json={
            "amount": 1.0, "base": "INR", "date": "2026-05-14",
            "rates": {"USD": 0.005, "EUR": 0.005, "GBP": 0.005},
        }))

    written: dict = {}
    monkeypatch.setattr("app.services.fx.service._write_live_raw",
                        lambda r, f: written.update({"rates": r}))

    with pytest.raises(SanityCapError) as exc:
        refresh_rates()
    assert "Sanity cap" in str(exc.value)
    # Nothing was written.
    assert "rates" not in written


@respx.mock
def test_refresh_first_fetch_skips_sanity_cap(db, monkeypatch):
    """No previous data → every rate is accepted. The cap only
    applies when there's a baseline to compare against."""
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: default)   # nothing stored

    respx.get(FRANKFURTER_URL).mock(
        return_value=httpx.Response(200, json=FRESH_RESPONSE))

    written: dict = {}
    monkeypatch.setattr("app.services.fx.service._write_live_raw",
                        lambda r, f: written.update({"rates": r}))

    result = refresh_rates()
    assert result.rejected_codes == []
    assert "USD" in written["rates"]
    assert "EUR" in written["rates"]


# ===================================================== effective rate

def _mock_settings(monkeypatch, **values):
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: values.get(k, default))


def test_effective_rate_inr_is_one(db):
    """INR always returns rate=1, source=INR."""
    eff = get_effective_rate("INR")
    assert eff.inr_per_unit == 1.0
    assert eff.source == RateSource.INR


def test_effective_rate_live_applies_markup(db, monkeypatch):
    """LIVE source: effective = raw × (1 + markup/100)."""
    fresh = datetime.now(timezone.utc).isoformat()
    _mock_settings(monkeypatch, **{
        "pricing.fx_live_raw":          {"USD": 83.33},
        "pricing.fx_live_fetched_at":   fresh,
        "pricing.fx_markup_percent":    5.0,
        "pricing.fx_overrides":         {},
    })
    eff = get_effective_rate("USD")
    assert eff.source == RateSource.LIVE
    assert eff.raw_inr_per_unit == 83.33
    assert abs(eff.inr_per_unit - 83.33 * 1.05) < 0.001
    assert eff.markup_percent == 5.0


def test_effective_rate_override_skips_markup(db, monkeypatch):
    """OVERRIDE source: admin's rate IS the effective rate. No markup."""
    _mock_settings(monkeypatch, **{
        "pricing.fx_live_raw":     {"USD": 83.33},   # live present
        "pricing.fx_markup_percent": 5.0,
        "pricing.fx_overrides":    {"USD": 90.0},    # but override wins
    })
    eff = get_effective_rate("USD")
    assert eff.source == RateSource.OVERRIDE
    assert eff.inr_per_unit == 90.0
    assert eff.markup_percent == 0.0
    assert eff.raw_inr_per_unit is None


def test_effective_rate_stale_when_old(db, monkeypatch):
    """Last-fetched > 7 days → source=STALE."""
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    _mock_settings(monkeypatch, **{
        "pricing.fx_live_raw":        {"USD": 83.33},
        "pricing.fx_live_fetched_at": old,
        "pricing.fx_markup_percent":  5.0,
        "pricing.fx_overrides":       {},
    })
    eff = get_effective_rate("USD")
    assert eff.source == RateSource.STALE
    # Markup still applies (the rate is just old, not wrong).
    assert abs(eff.inr_per_unit - 83.33 * 1.05) < 0.001


def test_effective_rate_unavailable_when_no_data(db, monkeypatch):
    """Neither live nor override → UNAVAILABLE."""
    _mock_settings(monkeypatch, **{
        "pricing.fx_live_raw": {"EUR": 90.0},
        "pricing.fx_overrides": {},
    })
    eff = get_effective_rate("USD")
    assert eff.source == RateSource.UNAVAILABLE


def test_effective_rate_empty_string_unavailable(db):
    """Empty / invalid code returns UNAVAILABLE — never raises."""
    eff = get_effective_rate("")
    assert eff.source == RateSource.UNAVAILABLE
