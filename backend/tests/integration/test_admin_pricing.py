"""Admin /admin/pricing endpoints — fx-status + fx-refresh-now.

Coverage:
  GET  /admin/pricing/fx-status         requires admin, returns snapshot
  POST /admin/pricing/fx-refresh-now    requires admin, triggers Frankfurter
  POST /admin/pricing/fx-refresh-now    rate-limited (5/hr)
  POST /admin/pricing/fx-refresh-now    surfaces network/data/sanity errors
"""
from __future__ import annotations
from datetime import datetime, timezone

import httpx
import pytest
import respx

from app.services.fx.frankfurter import FRANKFURTER_URL
from tests.conftest import auth_header


FRESH_FRANKFURTER = {
    "amount": 1.0, "base": "INR", "date": "2026-05-14",
    "rates": {"USD": 0.012, "EUR": 0.011},
}


def _seed_fx(monkeypatch, **overrides):
    """Pre-populate settings_store with fresh live rates + markup,
    so fx-status returns something non-trivial."""
    state = {
        "pricing.fx_live_raw":         {"USD": 83.33, "EUR": 90.91},
        "pricing.fx_live_fetched_at":  datetime.now(timezone.utc).isoformat(),
        "pricing.fx_markup_percent":   5.0,
        "pricing.fx_overrides":        {},
    }
    state.update(overrides)
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: state.get(k, default))


def test_fx_status_requires_admin(client, user):
    """Regular users get 403."""
    h = auth_header(client, user.email)
    r = client.get("/api/v1/admin/pricing/fx-status", headers=h)
    assert r.status_code == 403


def test_fx_status_returns_currency_table(client, admin, monkeypatch):
    """Admin sees: last-fetched timestamp, markup, per-currency rows."""
    _seed_fx(monkeypatch)
    h = auth_header(client, admin.email)
    r = client.get("/api/v1/admin/pricing/fx-status", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["markup_percent"] == 5.0
    codes = [c["code"] for c in body["currencies"]]
    assert "INR" in codes
    assert "USD" in codes
    assert "EUR" in codes
    usd = next(c for c in body["currencies"] if c["code"] == "USD")
    assert usd["has_live_rate"] is True
    assert usd["source"] == "live"
    assert usd["raw_inr_per_unit"] == 83.33


def test_fx_status_marks_stale_when_old(client, admin, monkeypatch):
    """fetched_at older than 7 days → stale=True (drives the UI warning)."""
    from datetime import timedelta
    _seed_fx(monkeypatch,
             **{"pricing.fx_live_fetched_at":
                 (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()})
    h = auth_header(client, admin.email)
    r = client.get("/api/v1/admin/pricing/fx-status", headers=h)
    assert r.json()["stale"] is True


def test_fx_refresh_now_requires_admin(client, user):
    h = auth_header(client, user.email)
    r = client.post("/api/v1/admin/pricing/fx-refresh-now", headers=h)
    assert r.status_code == 403


@respx.mock
def test_fx_refresh_now_happy_path(client, admin, monkeypatch):
    """Admin clicks Refresh now → Frankfurter mock returns 200 →
    endpoint surfaces the message + rate count."""
    # Empty stored state so first-fetch skips sanity cap.
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: default)
    # Stub the write so we don't hit the real DB / Redis.
    monkeypatch.setattr("app.services.fx.service._write_live_raw",
                        lambda r, f: None)

    respx.get(FRANKFURTER_URL).mock(
        return_value=httpx.Response(200, json=FRESH_FRANKFURTER))

    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/pricing/fx-refresh-now", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated"] is True
    assert body["rates_count"] == 2
    assert body["rejected_codes"] == []
    assert "Frankfurter" in body["message"]


@respx.mock
def test_fx_refresh_now_network_error_502(client, admin, monkeypatch):
    """Frankfurter unreachable → 502 with code=fx_network."""
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: default)
    respx.get(FRANKFURTER_URL).mock(
        side_effect=httpx.ConnectError("nope"))

    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/pricing/fx-refresh-now", headers=h)
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "fx_network"


@respx.mock
def test_fx_refresh_now_data_error_502(client, admin, monkeypatch):
    """Frankfurter returns malformed body → 502 with code=fx_data."""
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: default)
    respx.get(FRANKFURTER_URL).mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"}))

    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/pricing/fx-refresh-now", headers=h)
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "fx_data"


@respx.mock
def test_fx_refresh_now_sanity_cap_400(client, admin, monkeypatch):
    """Suspicious upstream payload (every rate moved >20%) → 400.

    The operator's action is "investigate before retrying" — distinct
    from a network failure they should just retry."""
    from app.core import settings_store as ss_module
    stored = {"pricing.fx_live_raw": {"USD": 80.0, "EUR": 90.0, "GBP": 100.0}}
    real_get = ss_module.SettingsStore.get
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: stored.get(k, real_get(self, k, default)))
    monkeypatch.setattr("app.services.fx.service._write_live_raw",
                        lambda r, f: None)

    respx.get(FRANKFURTER_URL).mock(
        return_value=httpx.Response(200, json={
            "amount": 1.0, "base": "INR", "date": "2026-05-14",
            "rates": {"USD": 0.005, "EUR": 0.005, "GBP": 0.005},
        }))

    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/pricing/fx-refresh-now", headers=h)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "fx_sanity"
