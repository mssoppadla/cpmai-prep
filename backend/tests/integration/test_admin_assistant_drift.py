"""Integration tests for /admin/assistant-drift dashboard API.

Pins:
  * RBAC — only admins/super-admins can read drift events
  * Aggregation — counts grouped by (flow, reason) match the seeded
    audit-log rows
  * Side-by-side comparison shape — the `totals.legacy` and
    `totals.agentic` keys both render even when agentic has no data
    yet (the headline "is the agentic flow better?" view depends on
    both columns being present from day one)
  * Filters — flow / reason / handler narrow the events list correctly
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models.assistant_log import AssistantLog
from app.models.audit_log import AuditLog
from tests.conftest import auth_header


def _seed_drift(db, *, action: str = "assistant.drift.refused_with_context",
                 flow: str = "legacy", handler: str = "faq",
                 reason: str = "refused_with_context",
                 minutes_ago: int = 5):
    """Helper — write a single drift audit_log row matching the shape
    the orchestrator's drift detector writes."""
    row = AuditLog(
        user_id=None,
        action=action,
        metadata_json={
            "flow": flow,
            "handler": handler,
            "intent": "FAQ",
            "drift_reason": reason,
            "severity": "warn",
            "detail": "test event",
            "retrieval_chunks_count": 3,
            "question_excerpt": "What are GDPR Rules?",
            "response_excerpt": "Outside the scope of CPMAI...",
        },
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )
    db.add(row); db.commit()
    return row


def _seed_assistant_turn(db, *, minutes_ago: int = 5):
    """Helper — write a single AssistantLog row so the summary's
    `totals.legacy.turns` denominator is non-zero (otherwise rate
    calculations on the frontend are undefined)."""
    row = AssistantLog(
        user_id=None, anon_id="test", intent="faq",
        intent_confidence=0.85, provider="openai", model="gpt-4o-mini",
        redacted_input="x", response_preview="y",
    )
    # created_at is server_default — patch via raw insert if testing
    # historical windows; for these tests the row's natural now() is fine.
    db.add(row); db.commit()
    return row


# ============================================================ RBAC

def test_drift_summary_requires_admin(client, user):
    """Regular users get 403 — drift events can leak production
    questions, must stay admin-only."""
    h = auth_header(client, user.email)
    r = client.get("/api/v1/admin/assistant-drift/summary", headers=h)
    assert r.status_code in (401, 403)


def test_drift_events_requires_admin(client, user):
    h = auth_header(client, user.email)
    r = client.get("/api/v1/admin/assistant-drift/events", headers=h)
    assert r.status_code in (401, 403)


# ============================================================ summary

def test_drift_summary_returns_zero_state_when_no_events(client, admin):
    """Cold start: no drift rows yet → both flows show 0 events.
    Frontend reads this as "drift detection is on but nothing's
    happened yet" — distinct from the agentic-not-active state."""
    h = auth_header(client, admin.email)
    r = client.get("/api/v1/admin/assistant-drift/summary?window=7d",
                   headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["window"] == "7d"
    assert body["totals"]["legacy"]["drift_events"] == 0
    assert body["totals"]["agentic"]["drift_events"] == 0
    # Side-by-side comparison structure must always be present so the
    # frontend can render both columns without a key-presence check.
    assert "agentic" in body["totals"]
    assert body["by_flow_reason"] == []


def test_drift_summary_aggregates_by_flow_and_reason(client, admin, db):
    """Seed events on legacy + (eventually) agentic flows; verify the
    counts roll up correctly per (flow, reason) pair. This is the
    eval data the dashboard's compare-flows view relies on."""
    # 3 refused-with-context on legacy
    for _ in range(3):
        _seed_drift(db, flow="legacy", reason="refused_with_context",
                     action="assistant.drift.refused_with_context")
    # 2 missing-citation on legacy
    for _ in range(2):
        _seed_drift(db, flow="legacy", reason="missing_citation",
                     action="assistant.drift.missing_citation")
    # 1 refused-with-context on agentic (simulating a future world
    # where the toggle's been on; pre-deployment this row would only
    # exist if drift_detection wrote `flow="agentic"` somewhere)
    _seed_drift(db, flow="agentic", reason="refused_with_context",
                 action="assistant.drift.refused_with_context")

    h = auth_header(client, admin.email)
    r = client.get("/api/v1/admin/assistant-drift/summary?window=7d",
                   headers=h)
    body = r.json()

    assert body["totals"]["legacy"]["drift_events"] == 5
    assert body["totals"]["agentic"]["drift_events"] == 1

    # by_flow_reason flat list — frontend uses this for the per-rule
    # breakdown column.
    pairs = {(r["flow"], r["reason"]): r["count"] for r in body["by_flow_reason"]}
    assert pairs[("legacy", "refused_with_context")] == 3
    assert pairs[("legacy", "missing_citation")] == 2
    assert pairs[("agentic", "refused_with_context")] == 1


# ============================================================ tool-usage

def _seed_agentic_turn(db, *, tools_called: list[dict],
                       minutes_ago: int = 5,
                       flow: str = "agentic"):
    """Helper — write a single ``assistant.agentic.turn`` audit row
    matching what AssistantOrchestrator._handle_agentic writes per
    agentic chat turn."""
    row = AuditLog(
        user_id=None,
        action="assistant.agentic.turn",
        metadata_json={
            "flow": flow,
            "tools_called": tools_called,
            "tools_planned": len(tools_called),
            "tools_executed": len(tools_called),
            "replans_fired": 0,
            "elapsed_ms": 1234,
            "phase": "synthesis",
            "error": None,
        },
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )
    db.add(row); db.commit()
    return row


def test_tool_usage_requires_admin(client, user):
    h = auth_header(client, user.email)
    r = client.get("/api/v1/admin/assistant-drift/tool-usage", headers=h)
    assert r.status_code in (401, 403)


def test_tool_usage_empty_window(client, admin):
    """Cold start: no agentic turns yet."""
    h = auth_header(client, admin.email)
    body = client.get(
        "/api/v1/admin/assistant-drift/tool-usage?window=7d",
        headers=h).json()
    assert body["total_turns"] == 0
    assert body["router_only_turns"] == 0
    assert body["tools"] == []


def test_tool_usage_aggregates_calls_and_turns(client, admin, db):
    """Two turns: turn 1 calls faq_search + content_search; turn 2
    calls faq_search again. Pin both counters: ``calls`` (every
    invocation) and ``turns_with`` (each tool once per turn)."""
    _seed_agentic_turn(db, tools_called=[
        {"name": "faq_search",     "status": "ok",
         "metadata": {"tool_elapsed_ms": 150}},
        {"name": "content_search", "status": "empty",
         "metadata": {"tool_elapsed_ms": 100}},
    ])
    _seed_agentic_turn(db, tools_called=[
        {"name": "faq_search", "status": "ok",
         "metadata": {"tool_elapsed_ms": 200}},
    ])

    h = auth_header(client, admin.email)
    body = client.get(
        "/api/v1/admin/assistant-drift/tool-usage", headers=h).json()

    assert body["total_turns"] == 2
    by_name = {t["name"]: t for t in body["tools"]}

    # faq_search called twice (once per turn), turns_with = 2.
    assert by_name["faq_search"]["calls"] == 2
    assert by_name["faq_search"]["turns_with"] == 2
    assert by_name["faq_search"]["by_status"] == {"ok": 2}

    # content_search called once.
    assert by_name["content_search"]["calls"] == 1
    assert by_name["content_search"]["turns_with"] == 1
    assert by_name["content_search"]["by_status"] == {"empty": 1}


def test_tool_usage_router_only_turns_counted_separately(
        client, admin, db,
):
    """A turn where the router answers without calling any tools is
    valuable signal — pin it as ``router_only_turns`` so the dashboard
    can show "X% of turns the router answered conversationally"."""
    _seed_agentic_turn(db, tools_called=[])
    _seed_agentic_turn(db, tools_called=[
        {"name": "faq_search", "status": "ok", "metadata": {}},
    ])

    h = auth_header(client, admin.email)
    body = client.get(
        "/api/v1/admin/assistant-drift/tool-usage", headers=h).json()
    assert body["total_turns"] == 2
    assert body["router_only_turns"] == 1
    # The router-only turn doesn't appear in any tool's count.
    assert sum(t["calls"] for t in body["tools"]) == 1


def test_tool_usage_latency_averaging(client, admin, db):
    """Per-tool average latency is computed from each invocation's
    metadata.tool_elapsed_ms. Pins the arithmetic."""
    _seed_agentic_turn(db, tools_called=[
        {"name": "faq_search", "status": "ok",
         "metadata": {"tool_elapsed_ms": 100}},
    ])
    _seed_agentic_turn(db, tools_called=[
        {"name": "faq_search", "status": "ok",
         "metadata": {"tool_elapsed_ms": 200}},
    ])
    _seed_agentic_turn(db, tools_called=[
        {"name": "faq_search", "status": "ok",
         "metadata": {"tool_elapsed_ms": 300}},
    ])

    h = auth_header(client, admin.email)
    body = client.get(
        "/api/v1/admin/assistant-drift/tool-usage", headers=h).json()
    faq = next(t for t in body["tools"] if t["name"] == "faq_search")
    assert faq["avg_latency_ms"] == 200   # (100+200+300)/3


def test_tool_usage_window_filter(client, admin, db):
    """A 25-hour-old agentic turn should NOT appear in the 24h window."""
    _seed_agentic_turn(
        db, tools_called=[
            {"name": "faq_search", "status": "ok", "metadata": {}}
        ],
        minutes_ago=60 * 25,
    )
    h = auth_header(client, admin.email)
    body = client.get(
        "/api/v1/admin/assistant-drift/tool-usage?window=24h",
        headers=h).json()
    assert body["total_turns"] == 0


def test_drift_summary_window_24h_excludes_older_events(client, admin, db):
    """Window narrowing: a 25-hour-old event should NOT appear in the
    24h window. Pins the time-filter behavior so the dashboard's
    "last 24h" toggle actually filters."""
    _seed_drift(db, minutes_ago=60 * 25)   # 25 hours ago

    h = auth_header(client, admin.email)
    r = client.get("/api/v1/admin/assistant-drift/summary?window=24h",
                   headers=h)
    body = r.json()
    assert body["totals"]["legacy"]["drift_events"] == 0


# ============================================================ events list

def test_drift_events_returns_recent_first(client, admin, db):
    """Sanity: most-recent first, oldest last."""
    _seed_drift(db, minutes_ago=60)
    _seed_drift(db, minutes_ago=10)   # newer
    _seed_drift(db, minutes_ago=120)  # older

    h = auth_header(client, admin.email)
    r = client.get("/api/v1/admin/assistant-drift/events", headers=h)
    body = r.json()
    assert body["count"] == 3
    # Newest event (10 minutes ago) first.
    times = [e["created_at"] for e in body["events"]]
    assert times == sorted(times, reverse=True)


def test_drift_events_filters_by_flow(client, admin, db):
    """flow=agentic must return only the agentic-flow rows. This is
    the click-through from the dashboard's "Agentic" column header."""
    _seed_drift(db, flow="legacy")
    _seed_drift(db, flow="agentic")
    _seed_drift(db, flow="legacy")

    h = auth_header(client, admin.email)
    r = client.get("/api/v1/admin/assistant-drift/events?flow=agentic",
                   headers=h)
    events = r.json()["events"]
    assert len(events) == 1
    assert events[0]["metadata"]["flow"] == "agentic"


def test_drift_events_filters_by_reason_with_or_without_prefix(
        client, admin, db):
    """The dashboard sends bare reasons ('refused_with_context');
    pin that we accept both bare AND fully-qualified
    ('assistant.drift.refused_with_context'). Operator-friendly."""
    _seed_drift(db, action="assistant.drift.refused_with_context",
                 reason="refused_with_context")
    _seed_drift(db, action="assistant.drift.empty_response",
                 reason="empty_response")

    h = auth_header(client, admin.email)
    bare = client.get(
        "/api/v1/admin/assistant-drift/events?reason=refused_with_context",
        headers=h).json()
    full = client.get(
        "/api/v1/admin/assistant-drift/events?"
        "reason=assistant.drift.refused_with_context",
        headers=h).json()
    assert bare["count"] == 1
    assert full["count"] == 1


def test_drift_events_filters_by_handler(client, admin, db):
    """handler=content narrows to only events from ContentHandler.
    Used by the dashboard's "drill into one handler" workflow."""
    _seed_drift(db, handler="faq")
    _seed_drift(db, handler="content")
    _seed_drift(db, handler="content")

    h = auth_header(client, admin.email)
    r = client.get("/api/v1/admin/assistant-drift/events?handler=content",
                   headers=h)
    body = r.json()
    assert body["count"] == 2
    assert all(e["metadata"]["handler"] == "content" for e in body["events"])


def test_drift_events_respects_limit(client, admin, db):
    h = auth_header(client, admin.email)
    for _ in range(15):
        _seed_drift(db)
    r = client.get("/api/v1/admin/assistant-drift/events?limit=5",
                   headers=h)
    body = r.json()
    assert body["count"] == 5
    assert body["limit"] == 5
