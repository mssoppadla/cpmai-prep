"""POST /api/v1/track — visitor-insights batched ingest.

Surface this test file pins:
  * Whitelist enforcement — unknown event names are dropped, not
    persisted, and don't 4xx the batch.
  * Batch cap — payloads above 50 events return 422.
  * PII strip on referrer query string.
  * Path normalisation — /courses/<slug> → /courses/[slug] in the
    persisted row.
  * Setting toggles — tracking.enabled=false and sample_rate=0 both
    write zero rows; the ack distinguishes the two reasons.
  * Both anon and authenticated users land in the same table; the
    authenticated user's user_id flows through to the row.
  * Metadata size cap — >4KB payloads are replaced with a truncation
    marker but the event still persists.

GeoIP + UA parsing are unit-tested separately in
test_tracking_ua_parser.py to keep this file focused on the HTTP
surface.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.models.journey_event import JourneyEvent
from app.services.geoip.domain import GeoLocation
from tests.conftest import auth_header


# ──────────────────────────── happy paths

def test_track_persists_known_events_with_normalised_path(client, db):
    """A batch with a known event lands as one row.

    The client (TrackerMount + deriveRouteTemplate) is the source of
    truth for the route template — it ships ``/courses/[slug]``
    directly. The server passes it through unchanged. This decouples
    the server from the route inventory so adding a new dynamic
    Next.js page requires zero backend change."""
    payload = {
        "events": [
            {
                "event": "page.view",
                "event_id": "11111111-1111-1111-1111-111111111111",
                "session_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "path": "/courses/[slug]",
                "referrer": "https://google.com/search?q=cpmai",
            }
        ]
    }
    # Both extract_client_ip AND geoip_lookup need patching: the test
    # client doesn't surface a usable client IP, and the endpoint
    # short-circuits the geoip branch when extract_client_ip returns
    # falsy. Mirrors the pattern in test_anonymous_traffic.py.
    with patch("app.api.v1.endpoints.tracking.extract_client_ip",
                return_value="203.0.113.7"), \
         patch("app.api.v1.endpoints.tracking.geoip_lookup",
                return_value=GeoLocation(country="IN", city="Bengaluru")):
        r = client.post("/api/v1/track", json=payload,
                        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/120"})
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] == 1
    assert body["dropped"] == 0

    rows = db.query(JourneyEvent).filter(JourneyEvent.event == "page.view").all()
    assert len(rows) == 1
    row = rows[0]
    assert row.path == "/courses/[slug]"
    assert row.country == "IN"
    assert row.city == "Bengaluru"
    assert row.device == "desktop"
    assert row.browser == "chrome"
    assert row.os == "windows"


def test_track_authenticated_user_gets_user_id(client, db, user):
    """An authenticated batch carries user_id through to the row.
    This is what enables 'paying customers about to churn' dashboards."""
    h = auth_header(client, user.email)
    with patch("app.api.v1.endpoints.tracking.geoip_lookup",
                return_value=None):
        r = client.post("/api/v1/track",
                        headers=h,
                        json={"events": [
                            {"event": "page.view",
                             "event_id": "22222222-2222-2222-2222-222222222222",
                             "path": "/dashboard"}
                        ]})
    assert r.status_code == 200
    assert r.json()["accepted"] == 1

    row = db.query(JourneyEvent).filter(JourneyEvent.event == "page.view").one()
    assert row.user_id == user.id


def test_track_batches_multiple_events_in_one_request(client, db):
    """The whole point of batching is one HTTP round-trip → many rows."""
    events = [
        {"event": "page.view", "event_id": f"{i:08d}-0000-0000-0000-000000000000",
         "path": "/", "session_id": "s1"} for i in range(5)
    ]
    with patch("app.api.v1.endpoints.tracking.geoip_lookup", return_value=None):
        r = client.post("/api/v1/track", json={"events": events})
    assert r.status_code == 200
    assert r.json()["accepted"] == 5
    assert db.query(JourneyEvent).count() == 5


# ──────────────────────────── whitelist

def test_track_drops_unknown_event_names(client, db):
    """Unknown event names are dropped — typo or malicious client
    shouldn't grow the event-name cardinality. The dropped event is
    counted in the ack so debugging is easy."""
    with patch("app.api.v1.endpoints.tracking.geoip_lookup", return_value=None):
        r = client.post("/api/v1/track", json={"events": [
            {"event": "totally.unknown", "event_id": "x",
             "path": "/"},
            {"event": "page.view", "event_id": "y",
             "path": "/"},
        ]})
    assert r.status_code == 200
    assert r.json() == {"accepted": 1, "dropped": 1, "reason": "ok"}
    # Only the page.view row should have been written
    events = [r.event for r in db.query(JourneyEvent).all()]
    assert events == ["page.view"]


# ──────────────────────────── kill switches

def test_track_disabled_kill_switch_writes_nothing(client, db, admin):
    """When tracking.enabled=false the endpoint drops the entire batch
    BEFORE any DB write — the ack reports reason='disabled' so the
    operator can confirm the kill switch is active.

    Uses the ``admin`` fixture (not a hardcoded user_id=1) so the
    system_settings FK constraint is satisfied — there's no guaranteed
    user with id=1 in the test DB."""
    # Drop any rows existing callers (auth, etc.) may have emitted so
    # the count assertion is clean.
    db.query(JourneyEvent).delete()
    db.commit()
    from app.core.settings_store import settings_store
    settings_store.set("tracking.enabled", False,
                        db=db, updated_by=admin.id)
    try:
        with patch("app.api.v1.endpoints.tracking.geoip_lookup", return_value=None):
            r = client.post("/api/v1/track", json={"events": [
                {"event": "page.view", "event_id": "z", "path": "/"}]})
        assert r.status_code == 200
        body = r.json()
        assert body == {"accepted": 0, "dropped": 1, "reason": "disabled"}
        assert db.query(JourneyEvent).count() == 0
    finally:
        settings_store.set("tracking.enabled", True,
                            db=db, updated_by=admin.id)


def test_track_zero_sample_rate_drops_batch(client, db, admin):
    """sample_rate=0.0 with any random roll drops the batch. We patch
    random so this is deterministic — sample_rate=0.0 means random()
    > 0 will always be true for any roll in [0,1)."""
    db.query(JourneyEvent).delete()
    db.commit()
    from app.core.settings_store import settings_store
    settings_store.set("tracking.sample_rate", 0.0,
                        db=db, updated_by=admin.id)
    try:
        with patch("app.api.v1.endpoints.tracking.geoip_lookup", return_value=None):
            r = client.post("/api/v1/track", json={"events": [
                {"event": "page.view", "event_id": "z", "path": "/"}]})
        assert r.status_code == 200
        assert r.json()["reason"] == "sampled_out"
        assert db.query(JourneyEvent).count() == 0
    finally:
        settings_store.set("tracking.sample_rate", 1.0,
                            db=db, updated_by=admin.id)


# ──────────────────────────── batch cap

def test_track_rejects_batch_above_50_events(client):
    """Pydantic validates max_length=50 on the events array. Anything
    bigger is a 422 — the client should never have shipped it."""
    payload = {"events": [
        {"event": "page.view", "event_id": f"e{i}", "path": "/"}
        for i in range(51)
    ]}
    r = client.post("/api/v1/track", json=payload)
    assert r.status_code == 422


# ──────────────────────────── path + referrer hygiene

def test_track_strips_pii_query_keys_from_referrer(client, db):
    """A referrer with ?email= in the query string must NOT be stored
    verbatim. The endpoint drops PII-looking keys before persisting."""
    with patch("app.api.v1.endpoints.tracking.geoip_lookup", return_value=None):
        r = client.post("/api/v1/track", json={"events": [
            {"event": "page.view", "event_id": "p1",
             "path": "/",
             "referrer": "https://example.com/x?utm_source=foo&email=bob@x.com"},
        ]})
    assert r.status_code == 200
    row = db.query(JourneyEvent).one()
    assert row.referrer is not None
    assert "email" not in row.referrer
    assert "utm_source=foo" in row.referrer


def test_track_passes_through_client_supplied_template(client, db):
    """The SPA tracker now derives the route template client-side
    (TrackerMount uses useParams()) and ships it as path. Server
    passes it through unchanged.

    Dashboard groups on path. Two visitors loading
    /courses/foo and /courses/bar both ship "/courses/[slug]" from
    the client, so the server stores one shared key — even though
    the server has no hardcoded knowledge of the /courses route."""
    with patch("app.api.v1.endpoints.tracking.geoip_lookup", return_value=None):
        client.post("/api/v1/track", json={"events": [
            {"event": "page.view", "event_id": "a", "path": "/courses/[slug]"},
            {"event": "page.view", "event_id": "b", "path": "/courses/[slug]"},
        ]})
    paths = sorted({r.path for r in db.query(JourneyEvent).all()})
    assert paths == ["/courses/[slug]"]


def test_track_collapses_likely_dynamic_segments_fallback(client, db):
    """If the client somehow ships a raw URL (legacy bookmark, future
    bug, or a backend-emitted event), the server fallback collapses
    clearly-dynamic segments so cardinality doesn't explode.

    This is the AUTOSCALE safety net — even routes never registered
    in any hardcoded list get sensible normalisation."""
    with patch("app.api.v1.endpoints.tracking.geoip_lookup", return_value=None):
        client.post("/api/v1/track", json={"events": [
            # Numeric id → [*]
            {"event": "page.view", "event_id": "x", "path": "/sessions/42"},
            {"event": "page.view", "event_id": "y", "path": "/sessions/99"},
            # Slug-like (12+ chars with digits) → [*]
            {"event": "page.view", "event_id": "z",
             "path": "/instructors/jane-doe-2025"},
            # Short literal segment → preserved
            {"event": "page.view", "event_id": "w", "path": "/about"},
        ]})
    paths = sorted({r.path for r in db.query(JourneyEvent).all()})
    # /sessions/42 and /sessions/99 collapse to one row
    assert "/sessions/[*]" in paths
    assert "/instructors/[*]" in paths
    assert "/about" in paths
    # No raw IDs leaked through
    assert not any("42" in p or "99" in p for p in paths)


# ──────────────────────────── metadata cap

def test_track_truncates_huge_metadata_but_keeps_event(client, db):
    """4KB cap on metadata — bigger payloads keep the event row but
    replace metadata with a {_truncated:true} marker so analytics
    aggregation still works."""
    huge = {"big": "x" * 8000}
    with patch("app.api.v1.endpoints.tracking.geoip_lookup", return_value=None):
        r = client.post("/api/v1/track", json={"events": [
            {"event": "cta.click", "event_id": "c", "path": "/",
             "metadata": huge},
        ]})
    assert r.status_code == 200
    row = db.query(JourneyEvent).one()
    assert row.event == "cta.click"
    assert row.metadata_json == {"_truncated": True}
