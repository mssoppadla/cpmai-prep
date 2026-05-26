"""End-to-end tests for /admin/insights/*.

Strategy: seed a known set of journey_events directly via SQLAlchemy
(faster than driving the SPA tracker through HTTP) then hit the
endpoints and assert on the aggregated output.

Surface pins:
  * RBAC — every endpoint requires admin
  * overview KPIs (sessions / visitors / bounce / conversion)
  * pages aggregation (views + bounce + exit)
  * funnel ordering + per-stage counts
  * session drilldown returns the full timeline ordered ascending
  * anonymize zeroes anon_id/session_id/ua/city but keeps event rows
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.journey_event import JourneyEvent
from tests.conftest import auth_header


def _clear_events(db):
    """Drop any journey_events rows that leaked in from previous test
    setup (notably the auth.login event the `auth_header` helper
    triggers when it logs in as admin). Each test that depends on
    exact counts calls this before seeding."""
    db.query(JourneyEvent).delete()
    db.commit()


def _seed(db, *, when, **kw):
    """Helper to insert one event row with sane defaults."""
    row = JourneyEvent(
        event=kw.pop("event"),
        tenant_id=kw.pop("tenant_id", 1),
        anon_id=kw.pop("anon_id", None),
        user_id=kw.pop("user_id", None),
        session_id=kw.pop("session_id", None),
        path=kw.pop("path", "/"),
        duration_ms=kw.pop("duration_ms", None),
        scroll_pct=kw.pop("scroll_pct", None),
        device=kw.pop("device", "desktop"),
        browser=kw.pop("browser", "chrome"),
        os=kw.pop("os", "windows"),
        country=kw.pop("country", "IN"),
        city=kw.pop("city", "Bengaluru"),
        ua=kw.pop("ua", "ua-string"),
        metadata_json=kw.pop("metadata", {}),
        created_at=when,
    )
    db.add(row)
    db.commit()
    return row


# ──────────────────────────── RBAC

ENDPOINTS = [
    "/api/v1/admin/insights/overview",
    "/api/v1/admin/insights/pages",
    "/api/v1/admin/insights/funnel",
]


@pytest.mark.parametrize("ep", ENDPOINTS)
def test_endpoints_require_admin(client, user, ep):
    """Non-admin → 403 on every insights endpoint."""
    h = auth_header(client, user.email)
    r = client.get(ep, headers=h)
    assert r.status_code == 403


@pytest.mark.parametrize("ep", ENDPOINTS)
def test_endpoints_reject_anon(client, ep):
    r = client.get(ep)
    assert r.status_code in (401, 403)


# ──────────────────────────── /overview

def test_overview_counts_sessions_visitors_and_bounces(client, db, admin):
    """One bouncing session (one page.view), one engaged session (two
    page.views + payment), should give us sessions=2, visitors=2,
    bounce=0.5, conversion=0.5."""
    # Important order: login first (which emits auth.login → pollutes
    # the count) THEN clear, THEN seed our controlled events.
    h = auth_header(client, admin.email)
    _clear_events(db)
    now = datetime.now(timezone.utc) - timedelta(hours=1)

    # Bouncer: visitor A, one page.view only
    _seed(db, when=now, event="page.view",
          anon_id="a-bouncer", session_id="s-bouncer", path="/")
    _seed(db, when=now + timedelta(seconds=30), event="page.exit",
          anon_id="a-bouncer", session_id="s-bouncer", path="/",
          duration_ms=30000)
    _seed(db, when=now + timedelta(seconds=31), event="session.end",
          anon_id="a-bouncer", session_id="s-bouncer", path="/")

    # Converter: visitor B, two page.views + payment
    _seed(db, when=now + timedelta(minutes=5), event="page.view",
          anon_id="a-buyer", session_id="s-buyer", path="/")
    _seed(db, when=now + timedelta(minutes=6), event="page.view",
          anon_id="a-buyer", session_id="s-buyer", path="/pricing")
    _seed(db, when=now + timedelta(minutes=7), event="payment.success",
          anon_id="a-buyer", session_id="s-buyer", path="/pricing")
    _seed(db, when=now + timedelta(minutes=8), event="page.exit",
          anon_id="a-buyer", session_id="s-buyer", path="/pricing",
          duration_ms=60000)

    r = client.get("/api/v1/admin/insights/overview?window=24h", headers=h)
    assert r.status_code == 200
    kpi = r.json()["kpi"]
    assert kpi["sessions"] == 2
    assert kpi["visitors"] == 2
    assert kpi["page_views"] == 3
    assert kpi["bounce_rate"] == 0.5
    assert kpi["conversion_rate"] == 0.5
    assert kpi["avg_pages_per_session"] == 1.5


# ──────────────────────────── /pages

def test_pages_ranks_by_views_and_computes_avg_time(client, db, admin):
    """Pages endpoint should rank by view count and compute avg
    active time from page.exit duration_ms."""
    now = datetime.now(timezone.utc) - timedelta(hours=1)
    # Two views of "/" (avg duration 20s + 40s = 30s)
    for i, dur in enumerate([20_000, 40_000]):
        _seed(db, when=now + timedelta(minutes=i), event="page.view",
              anon_id=f"v{i}", session_id=f"s{i}", path="/")
        _seed(db, when=now + timedelta(minutes=i, seconds=30),
              event="page.exit",
              anon_id=f"v{i}", session_id=f"s{i}", path="/",
              duration_ms=dur)
    # One view of "/pricing"
    _seed(db, when=now, event="page.view",
          anon_id="v-pricing", session_id="s-pricing", path="/pricing")

    h = auth_header(client, admin.email)
    r = client.get("/api/v1/admin/insights/pages?window=24h", headers=h)
    assert r.status_code == 200
    pages = r.json()["pages"]
    assert pages[0]["path"] == "/"
    assert pages[0]["views"] == 2
    assert pages[0]["avg_seconds"] == 30.0
    assert pages[0]["unique_visitors"] == 2
    assert pages[1]["path"] == "/pricing"


# ──────────────────────────── /funnel

def test_funnel_counts_visitors_at_each_stage(client, db, admin):
    """Funnel reports absolute visitors per stage independently."""
    now = datetime.now(timezone.utc) - timedelta(hours=1)
    # 3 visitors land
    for v in ("v1", "v2", "v3"):
        _seed(db, when=now, event="page.view", anon_id=v, path="/")
    # 2 of them sign up
    for v in ("v1", "v2"):
        _seed(db, when=now + timedelta(minutes=1), event="auth.signup",
              anon_id=v, path="/signup")
    # 1 of them views a lesson
    _seed(db, when=now + timedelta(minutes=2), event="page.view",
          anon_id="v1", path="/courses/[slug]/lessons/[id]")
    # 1 of them pays
    _seed(db, when=now + timedelta(minutes=3), event="payment.success",
          anon_id="v1", path="/checkout")

    h = auth_header(client, admin.email)
    r = client.get("/api/v1/admin/insights/funnel?window=24h", headers=h)
    assert r.status_code == 200
    stages = r.json()["stages"]
    assert [s["visitors"] for s in stages] == [3, 2, 1, 1]
    # Overall = last/first = 1/3
    assert abs(r.json()["overall_conversion"] - 1/3) < 0.001


# ──────────────────────────── /sessions/{anon_id}

def test_session_timeline_returns_ordered_events(client, db, admin):
    """Drilldown returns events in chronological order. 404 on no events."""
    now = datetime.now(timezone.utc) - timedelta(hours=1)
    anon = "drill-me-please"
    _seed(db, when=now, event="page.view", anon_id=anon, path="/", session_id="s1")
    _seed(db, when=now + timedelta(seconds=10), event="page.view",
          anon_id=anon, path="/pricing", session_id="s1")
    _seed(db, when=now + timedelta(seconds=20), event="cta.click",
          anon_id=anon, path="/pricing", session_id="s1",
          metadata={"cta": "buy_pro"})

    h = auth_header(client, admin.email)
    r = client.get(f"/api/v1/admin/insights/sessions/{anon}", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["event_count"] == 3
    events = body["events"]
    # Ascending order
    assert events[0]["event"] == "page.view"
    assert events[-1]["event"] == "cta.click"
    assert events[-1]["metadata"]["cta"] == "buy_pro"


def test_session_timeline_404_when_unknown(client, db, admin):
    h = auth_header(client, admin.email)
    r = client.get("/api/v1/admin/insights/sessions/never-seen", headers=h)
    assert r.status_code == 404


# ──────────────────────────── /anonymize

def test_anonymize_zeroes_pii_but_keeps_event_rows(client, db, admin):
    """GDPR — anon_id is unlinked, but the event row (with country/
    event/path) stays so aggregate counts don't shift."""
    h = auth_header(client, admin.email)
    _clear_events(db)
    now = datetime.now(timezone.utc) - timedelta(hours=1)
    anon = "delete-me"
    _seed(db, when=now, event="page.view", anon_id=anon, session_id="s",
          path="/", ua="orig-ua", city="Mumbai")
    _seed(db, when=now + timedelta(seconds=1), event="page.view",
          anon_id=anon, session_id="s", path="/pricing",
          ua="orig-ua", city="Mumbai")

    r = client.post(f"/api/v1/admin/insights/anonymize/{anon}", headers=h)
    assert r.status_code == 200
    assert r.json()["rows_affected"] == 2

    # The rows are still there
    remaining = db.query(JourneyEvent).all()
    assert len(remaining) == 2
    for row in remaining:
        # … but the identifying fields are zeroed
        assert row.anon_id is None
        assert row.session_id is None
        assert row.ua is None
        assert row.city is None
        # … and the non-PII fields stay (so aggregates work)
        assert row.event == "page.view"
        assert row.country == "IN"
