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
  - by_region preserves null (unresolved IPs) as a distinct bucket
  - by_region groups on (country, city) so cities surface separately
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
# The summary now rolls up journey_events (known vs anonymous), not the
# assistant audit pings. Classification: user_id → known; anon_id
# linked in anon_identity_links AND event after linked_at → known;
# linked but event pre-dates the link → anonymous + counted in
# signed_up; unlinked → anonymous.

from app.models.anon_identity_link import AnonIdentityLink
from app.models.journey_event import JourneyEvent


def _seed_journey(db, *, user_id=None, anon_id=None,
                  country="IN", city="Bengaluru",
                  minutes_ago=5, event="page.view"):
    row = JourneyEvent(
        event=event, user_id=user_id, anon_id=anon_id,
        country=country, city=city,
        created_at=datetime.now(timezone.utc)
        - timedelta(minutes=minutes_ago),
    )
    db.add(row); db.commit()
    return row


def _link(db, anon_id, user_id, minutes_ago=0):
    db.add(AnonIdentityLink(
        anon_id=anon_id, user_id=user_id,
        linked_at=datetime.now(timezone.utc)
        - timedelta(minutes=minutes_ago)))
    db.commit()


def test_summary_with_no_visitor_traffic(client, admin):
    # NOTE: auth_header logs the admin in, which itself emits an
    # auth.login journey event — the admin IS a known visitor in the
    # window. That's correct behavior, so the baseline here is 1 known
    # user, not zero.
    h = auth_header(client, admin.email)
    body = client.get("/api/v1/admin/anonymous-traffic/summary?window=7d",
                      headers=h).json()
    assert body["totals"] == {"known_users": 1, "anonymous": 0,
                              "signed_up": 0, "returning_anonymous": 0,
                              "events": 1}
    # by_day always populated (zero-filled) — 7 days + today = 8.
    assert len(body["by_day"]) == 8


def test_summary_counts_known_and_anonymous_separately(client, admin,
                                                       user, db):
    _seed_journey(db, user_id=user.id)                 # known (signed in)
    _seed_journey(db, user_id=user.id)                 # same user — dedupe
    _seed_journey(db, anon_id="anon-A")                # anonymous
    _seed_journey(db, anon_id="anon-A")                # same browser — dedupe
    _seed_journey(db, anon_id="anon-B", country="US", city="Seattle")

    h = auth_header(client, admin.email)
    body = client.get("/api/v1/admin/anonymous-traffic/summary",
                      headers=h).json()
    assert body["totals"]["known_users"] == 2   # seeded user + admin login
    assert body["totals"]["anonymous"] == 2
    assert body["totals"]["signed_up"] == 0
    assert body["totals"]["events"] == 6        # 5 seeded + admin login
    by_region = {(r["country"], r["city"]): r for r in body["by_region"]}
    assert by_region[("IN", "Bengaluru")]["known_users"] == 1
    assert by_region[("IN", "Bengaluru")]["anonymous"] == 1
    assert by_region[("US", "Seattle")]["anonymous"] == 1


def test_summary_signed_up_keeps_historical_anon_count(client, admin,
                                                       user, db):
    """The owner's rule: don't rewrite history when someone signs up.
    Pre-link anon events still count the visitor as anonymous, but the
    payload says how many of them have since signed up."""
    _seed_journey(db, anon_id="anon-conv", minutes_ago=120)  # browsed…
    _link(db, "anon-conv", user.id, minutes_ago=60)          # …signed up
    _seed_journey(db, anon_id="anon-stay", minutes_ago=90)   # never did

    h = auth_header(client, admin.email)
    body = client.get("/api/v1/admin/anonymous-traffic/summary",
                      headers=h).json()
    assert body["totals"]["anonymous"] == 2      # history not rewritten
    assert body["totals"]["signed_up"] == 1      # "1 of 2 signed up"
    assert body["totals"]["known_users"] == 1    # only the admin's login


def test_summary_linked_browser_counts_known_after_link(client, admin,
                                                        user, db):
    """A previously-signed-up browser revisiting — even signed out —
    counts as a KNOWN user's visit from linked_at forward."""
    _link(db, "anon-known", user.id, minutes_ago=60)
    _seed_journey(db, anon_id="anon-known", minutes_ago=5)   # after link

    h = auth_header(client, admin.email)
    body = client.get("/api/v1/admin/anonymous-traffic/summary",
                      headers=h).json()
    assert body["totals"]["known_users"] == 2   # linked browser + admin
    assert body["totals"]["anonymous"] == 0
    assert body["totals"]["signed_up"] == 0


def test_summary_returning_anonymous_across_days(client, admin, db):
    """Same unlinked browser on 2+ distinct days = returning."""
    _seed_journey(db, anon_id="anon-ret", minutes_ago=60 * 26)  # 2 days ago
    _seed_journey(db, anon_id="anon-ret", minutes_ago=5)        # today
    _seed_journey(db, anon_id="anon-one", minutes_ago=5)        # single day

    h = auth_header(client, admin.email)
    body = client.get("/api/v1/admin/anonymous-traffic/summary?window=7d",
                      headers=h).json()
    assert body["totals"]["anonymous"] == 2
    assert body["totals"]["returning_anonymous"] == 1


def test_summary_window_24h_excludes_older(client, admin, db):
    _seed_journey(db, anon_id="anon-old", minutes_ago=60 * 25)
    h = auth_header(client, admin.email)
    body = client.get("/api/v1/admin/anonymous-traffic/summary?window=24h",
                      headers=h).json()
    assert body["totals"]["anonymous"] == 0


def test_summary_by_day_fills_zero_count_gaps(client, admin, db):
    _seed_journey(db, anon_id="anon-today", minutes_ago=10)
    h = auth_header(client, admin.email)
    body = client.get("/api/v1/admin/anonymous-traffic/summary?window=7d",
                      headers=h).json()
    days = body["by_day"]
    assert len(days) == 8
    # Today carries the seeded anon event + the admin's login; every
    # other day is zero-filled.
    nonzero = [d for d in days if d["events"] > 0]
    assert len(nonzero) == 1
    assert nonzero[0]["anonymous"] == 1 and nonzero[0]["known_users"] == 1


def test_summary_response_shape(client, admin, user, db):
    _seed_journey(db, user_id=user.id)
    h = auth_header(client, admin.email)
    body = client.get("/api/v1/admin/anonymous-traffic/summary",
                      headers=h).json()
    assert set(body.keys()) >= {"window", "since", "totals",
                                "by_region", "by_day"}
    assert set(body["totals"].keys()) == {
        "known_users", "anonymous", "signed_up",
        "returning_anonymous", "events"}
    assert set(body["by_region"][0].keys()) == {
        "country", "city", "events", "known_users", "anonymous"}
    assert set(body["by_day"][0].keys()) == {
        "day", "events", "known_users", "anonymous"}


def test_summary_backfilled_prelogin_events_stay_anonymous(client, admin,
                                                           user, db):
    """Login backfills user_id onto pre-login rows for the profile
    timeline — but the widget must NOT reclassify them: pre-link
    events stay anonymous history, surfacing only via signed_up."""
    _seed_journey(db, anon_id="anon-bf", user_id=user.id,
                  minutes_ago=120)                       # backfilled row
    _link(db, "anon-bf", user.id, minutes_ago=60)        # signed up later
    _seed_journey(db, anon_id="anon-bf", user_id=user.id,
                  minutes_ago=5)                         # post-link visit

    h = auth_header(client, admin.email)
    body = client.get("/api/v1/admin/anonymous-traffic/summary",
                      headers=h).json()
    assert body["totals"]["anonymous"] == 1      # the pre-link visit
    assert body["totals"]["signed_up"] == 1
    assert body["totals"]["known_users"] == 2    # user (post-link) + admin
