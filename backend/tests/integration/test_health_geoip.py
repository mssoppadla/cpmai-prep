"""The /health endpoint must include a geoip status block AND must
never 500 even when geoip is broken.

We test:

  1. With a normal (degraded) state — no mmdb installed — /health
     returns 200 with geoip.database_present=False.
  2. If geoip.get_status() raises (a hypothetical regression), /health
     still returns 200 with safe defaults — does NOT propagate the
     error.

Both are part of the health-endpoint contract: it's hit by uptime
monitors, by Caddy's healthcheck, by the deploy-time smoke test. A
500 here = deploy rolls back = nobody can ship until it's fixed.
"""
from __future__ import annotations
from unittest.mock import patch


def test_health_includes_geoip_block(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "geoip" in body
    assert "database_present" in body["geoip"]
    assert "stale" in body["geoip"]


def test_health_survives_geoip_exception(client):
    """If the geoip module is unimportable or get_status() raises for
    any reason, /health must NOT 500. It falls back to the safe defaults
    in main.py's except block."""
    with patch("app.services.geoip.get_status",
               side_effect=RuntimeError("boom")):
        r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["geoip"]["database_present"] is False
    assert body["geoip"]["stale"] is False
