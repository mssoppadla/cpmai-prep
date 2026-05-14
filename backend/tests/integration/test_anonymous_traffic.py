"""Anonymous-visitor tracking end-to-end:

  * POST /assistant/anon-event — fired when an anon user opens the
    chat widget. Records one audit_logs row with geoip-derived
    country/city + the anon_id from middleware.

  * GET /admin/anonymous-traffic/summary — aggregates those rows by
    (country, day) so the /admin/leads page can render an unconverted-
    traffic dashboard.

Test surface pins:
  - RBAC (admin-only summary endpoint; chat endpoint open to all)
  - Authenticated users hitting anon-event don't get tracked
  - GeoIP lookup is best-effort (lookup failure → event still recorded)
  - Aggregation correctly de-dupes per anon_id
  - by_day fills zero-count gap days so the chart renders continuously
  - by_country preserves null (unresolved IPs) as a distinct bucket
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.audit_log import AuditLog
from app.services.geoip.domain import GeoLocation
from tests.conftest import auth_header


# ============================================================ /anon-event

def test_anon_event_writes_audit_log_row(client, db):
    """Happy path: anon visitor clicks bubble → one audit_logs row
    with action 'assistant.anon.bubble_open' and geoip-enriched
    metadata.

    We patch BOTH extract_client_ip (test client doesn't surface a
    usable client IP) AND geoip_lookup (don't depend on the GeoIP DB
    being present in test envs). The endpoint's geoip path only fires
    when extract_client_ip returns truthy."""
    with patch("app.api.v1.endpoints.assistant.extract_client_ip",
                return_value="203.0.113.7"), \
         patch("app.api.v1.endpoints.assistant.geoip_lookup",
                return_value=GeoLocation(country="IN", city="Bengaluru")):
        r = client.post("/api/v1/assistant/anon-event",
                         json={"kind": "bubble_open"})
    assert r.status_code == 204

    rows = (db.query(AuditLog)
            .filter(AuditLog.action.like("assistant.anon.%"))
            .all())
    assert len(rows) == 1
    row = rows[0]
    assert row.action == "assistant.anon.bubble_open"
    assert row.user_id is None
    assert row.metadata_json["country"] == "IN"
    assert row.metadata_json["city"] == "Bengaluru"


def test_anon_event_authenticated_user_is_a_noop(client, db, user):
    """Authenticated users aren't 'anonymous' by definition. The
    endpoint short-circuits and writes nothing — but returns 204 so
    the frontend doesn't need to know whether the user signed in
    mid-session."""
    h = auth_header(client, user.email)
    r = client.post("/api/v1/assistant/anon-event", headers=h,
                     json={"kind": "bubble_open"})
    assert r.status_code == 204
    assert db.query(AuditLog).filter(
        AuditLog.action.like("assistant.anon.%")).count() == 0


def test_anon_event_records_even_when_geoip_returns_nothing(client, db):
    """GeoIP lookup is best-effort. If the IP doesn't resolve (private
    IP, datacenter, lookup service down), still record the event —
    just with country/city as None. The dashboard surfaces null-
    country events as a distinct bucket on purpose."""
    with patch("app.api.v1.endpoints.assistant.geoip_lookup",
                return_value=None):
        r = client.post("/api/v1/assistant/anon-event",
                         json={"kind": "bubble_open"})
    assert r.status_code == 204

    rows = (db.query(AuditLog)
            .filter(AuditLog.action.like("assistant.anon.%")).all())
    assert len(rows) == 1
    assert rows[0].metadata_json["country"] is None
    assert rows[0].metadata_json["city"] is None


def test_anon_event_sanitises_kind_to_alphanumeric(client, db):
    """The `kind` field goes into the action column suffix. Sanitise
    so a crafted client can't pollute the action namespace with
    'bubble_open; DROP TABLE...' or similar. Garbage in → 'unknown'."""
    with patch("app.api.v1.endpoints.assistant.geoip_lookup",
                return_value=None):
        client.post("/api/v1/assistant/anon-event",
                    json={"kind": "bubble; DROP TABLE users;--"})
    rows = (db.query(AuditLog)
            .filter(AuditLog.action.like("assistant.anon.%")).all())
    assert len(rows) == 1
    # Only alphanumeric + underscore survive sanitisation.
    assert rows[0].action == "assistant.anon.bubbleDROPTABLEusers"


def test_anon_event_empty_kind_falls_back_to_unknown(client, db):
    with patch("app.api.v1.endpoints.assistant.geoip_lookup",
                return_value=None):
        client.post("/api/v1/assistant/anon-event", json={"kind": ""})
    rows = (db.query(AuditLog)
            .filter(AuditLog.action.like("assistant.anon.%")).all())
    assert len(rows) == 1
    assert rows[0].action == "assistant.anon.unknown"


# ============================================================ /summary RBAC

def test_summary_requires_admin(client, user):
    """Anonymous-traffic data could leak conversion-rate intel —
    admin-only."""
    h = auth_header(client, user.email)
    r = client.get("/api/v1/admin/anonymous-traffic/summary", headers=h)
    assert r.status_code in (401, 403)


# ============================================================ /summary aggregation

def _seed_anon_event(db, *, anon_id: str | None = "anon-1",
                      country: str | None = "IN",
                      city: str | None = "Bengaluru",
                      kind: str = "bubble_open",
                      minutes_ago: int = 5):
    """Direct DB write matching the shape /anon-event would have produced.
    Keeps the aggregation tests independent of the endpoint."""
    row = AuditLog(
        user_id=None,
        action=f"assistant.anon.{kind}",
        metadata_json={"anon_id": anon_id, "country": country, "city": city},
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )
    db.add(row); db.commit()
    return row


def test_summary_empty_when_no_events(client, admin):
    h = auth_header(client, admin.email)
    r = client.get("/api/v1/admin/anonymous-traffic/summary?window=7d",
                   headers=h)
    body = r.json()
    assert body["totals"]["unique_anons"] == 0
    assert body["totals"]["events"] == 0
    assert body["by_country"] == []
    # by_day is always populated (even with zeros) so the chart
    # renders a continuous timeline. 7 days + today = 8 buckets.
    assert len(body["by_day"]) == 8
    assert all(d["events"] == 0 for d in body["by_day"])


def test_summary_dedupes_unique_anons(client, admin, db):
    """Same browser opening the bubble 5 times in a session counts as
    1 unique anon, not 5. Distinguishes 'high-intent' single anons
    from genuine multi-visitor traffic."""
    for _ in range(5):
        _seed_anon_event(db, anon_id="anon-A", country="IN")
    _seed_anon_event(db, anon_id="anon-B", country="IN")

    h = auth_header(client, admin.email)
    body = client.get("/api/v1/admin/anonymous-traffic/summary",
                       headers=h).json()
    assert body["totals"]["unique_anons"] == 2
    assert body["totals"]["events"] == 6
    assert body["by_country"] == [
        {"country": "IN", "events": 6, "unique_anons": 2},
    ]


def test_summary_groups_by_country(client, admin, db):
    _seed_anon_event(db, anon_id="anon-IN1", country="IN")
    _seed_anon_event(db, anon_id="anon-IN2", country="IN")
    _seed_anon_event(db, anon_id="anon-US1", country="US")
    _seed_anon_event(db, anon_id="anon-noip", country=None)

    h = auth_header(client, admin.email)
    body = client.get("/api/v1/admin/anonymous-traffic/summary",
                       headers=h).json()
    by_country = {c["country"]: c for c in body["by_country"]}
    assert by_country["IN"]["events"] == 2
    assert by_country["IN"]["unique_anons"] == 2
    assert by_country["US"]["events"] == 1
    # Null IPs (private/datacenter) preserved as a distinct bucket so
    # operators can spot them rather than them silently hiding.
    assert by_country[None]["events"] == 1


def test_summary_window_24h_excludes_older(client, admin, db):
    """24h window must drop a 25h-old event."""
    _seed_anon_event(db, minutes_ago=60 * 25)   # 25 hours ago
    h = auth_header(client, admin.email)
    body = client.get("/api/v1/admin/anonymous-traffic/summary?window=24h",
                       headers=h).json()
    assert body["totals"]["unique_anons"] == 0


def test_summary_by_day_fills_zero_count_gaps(client, admin, db):
    """The frontend renders by_day as a bar chart — fill zero-count
    days so the chart doesn't skip gaps. Regression guard: this is
    the subtle "missing zero bars look like missing data" bug."""
    # Today only — no events on the other 6 days of the 7d window.
    _seed_anon_event(db, minutes_ago=10)

    h = auth_header(client, admin.email)
    body = client.get("/api/v1/admin/anonymous-traffic/summary?window=7d",
                       headers=h).json()
    days = body["by_day"]
    assert len(days) == 8   # 7 days + today
    # Exactly one day has events; the rest are zero.
    nonzero_days = [d for d in days if d["events"] > 0]
    assert len(nonzero_days) == 1
    assert nonzero_days[0]["events"] == 1


def test_summary_response_shape(client, admin, db):
    """Pin the response keys so the frontend can rely on shape."""
    _seed_anon_event(db, country="IN")
    h = auth_header(client, admin.email)
    body = client.get("/api/v1/admin/anonymous-traffic/summary",
                       headers=h).json()
    assert set(body.keys()) >= {
        "window", "since", "totals", "by_country", "by_day"
    }
    assert set(body["totals"].keys()) == {"unique_anons", "events"}
