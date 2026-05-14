"""Drift dashboard API — read-only views over the assistant.drift.* rows
written by the orchestrator's post-check.

Two endpoints, both admin-only:

  * ``GET /admin/assistant-drift/summary?window=...`` — aggregated
    counts grouped by ``flow`` (legacy / agentic) and ``reason``.
    Powers the side-by-side comparison cards on the dashboard:
    "in the last 7 days, how many drift events of each type fired
    on each flow, and what's that as a rate of total turns?"

  * ``GET /admin/assistant-drift/events?...`` — paginated recent
    events with full metadata for investigation. Supports filters
    on flow, reason, handler so an operator can drill into a
    specific signature ("show me all refused-with-context events
    on the FAQ handler this week").

Schema reuses ``audit_logs`` — drift events live alongside the rest
of the audit trail under the ``assistant.drift.*`` action prefix.
The (created_at, action) index already exists for /admin/audit-logs,
so these queries piggyback on it without new migrations.

Why aggregation server-side rather than ship raw rows + group on the
frontend: the dashboard renders four metric panels per flow per
window. Pulling 10k raw rows just to count them client-side is
wasteful when Postgres can return four pre-aggregated numbers.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_admin_user, get_db
from app.models.assistant_log import AssistantLog
from app.models.audit_log import AuditLog
from app.models.user import User

router = APIRouter()


# Time-window aliases the dashboard exposes. Limited set so the
# (created_at, action) index can serve every query — no surprise full
# table scans from a wild user-supplied window.
_WINDOW_TO_DELTA = {
    "24h": timedelta(hours=24),
    "7d":  timedelta(days=7),
    "30d": timedelta(days=30),
}
WindowLiteral = Literal["24h", "7d", "30d"]


# Drift action prefix — every drift event's action is
# ``assistant.drift.{reason}``. Used to scope queries off the
# audit_logs index without scanning the whole table.
_DRIFT_ACTION_PREFIX = "assistant.drift."


@router.get("/summary")
def drift_summary(
    window: WindowLiteral = Query("7d"),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_admin_user),
):
    """Aggregated drift counts for the dashboard's headline cards.

    Returns side-by-side numbers for every (flow, reason) combination
    plus the total number of assistant turns in the window — so the
    frontend can render rates ("12 refused-with-context events out of
    1,043 turns = 1.15%").

    Example payload::

        {
          "window": "7d",
          "since":  "2026-05-07T13:00:00Z",
          "totals": {
            "legacy":  {"turns": 1043, "drift_events": 12},
            "agentic": {"turns": 412,  "drift_events": 4}
          },
          "by_flow_reason": [
            {"flow": "legacy", "reason": "refused_with_context", "count": 8},
            {"flow": "legacy", "reason": "missing_citation",     "count": 2},
            ...
          ]
        }

    When the agentic toggle isn't enabled yet (the case for now),
    ``agentic.turns == 0`` and ``by_flow_reason`` has no
    ``flow="agentic"`` entries. The frontend renders that column as
    "— not active" instead of misleading 0% / 0% rates.
    """
    delta = _WINDOW_TO_DELTA[window]
    since = datetime.now(timezone.utc) - delta

    # Pull every drift row in the window, aggregate in Python.
    # At our scale (target: 100 users, ~few hundred drift events per
    # week max) this is sub-millisecond. If volume ever grows past
    # ~50k events per window, swap to a Postgres-side aggregation
    # using the JSON-extract operator (metadata->>'flow').
    rows = (db.query(AuditLog)
            .filter(AuditLog.action.like(_DRIFT_ACTION_PREFIX + "%"))
            .filter(AuditLog.created_at >= since)
            .all())

    by_fr: dict[tuple[str, str], int] = defaultdict(int)
    for r in rows:
        meta = r.metadata_json or {}
        flow   = meta.get("flow") or "legacy"
        reason = meta.get("drift_reason") or "unknown"
        by_fr[(flow, reason)] += 1

    drift_by_flow: dict[str, int] = defaultdict(int)
    for (flow, _r), c in by_fr.items():
        drift_by_flow[flow] += c

    # Per-flow turn counts. AssistantOrchestrator writes
    # ``intent="agentic"`` on the AssistantLog row for agentic turns;
    # legacy turns use one of the five handler-intent values. We split
    # by that column. Shadow-mode does NOT write AssistantLog rows
    # (only audit_log shadow rows), so shadow_agentic.turns is null —
    # frontend renders the shadow bucket as "drift events only, no
    # turn-count base for a rate".
    legacy_turns = db.query(func.count(AssistantLog.id)).filter(
        AssistantLog.created_at >= since,
        AssistantLog.intent != "agentic",
    ).scalar() or 0
    agentic_turns = db.query(func.count(AssistantLog.id)).filter(
        AssistantLog.created_at >= since,
        AssistantLog.intent == "agentic",
    ).scalar() or 0

    totals: dict[str, dict] = {
        "legacy": {
            "turns":        int(legacy_turns),
            "drift_events": drift_by_flow.get("legacy", 0),
        },
        "agentic": {
            "turns":        int(agentic_turns),
            "drift_events": drift_by_flow.get("agentic", 0),
        },
    }
    # Surface shadow_agentic only when we actually saw shadow events
    # in the window. Empty shadow column would just be visual noise.
    shadow_drift = drift_by_flow.get("shadow_agentic", 0)
    if shadow_drift > 0:
        totals["shadow_agentic"] = {
            # Shadow turns don't write AssistantLog rows by design
            # (the user only has one turn_id; shadow is a side-channel).
            # No rate calculation possible — frontend renders as count
            # only with a "shadow has no turn baseline" footnote.
            "turns":        None,
            "drift_events": shadow_drift,
        }

    return {
        "window": window,
        "since":  since.isoformat().replace("+00:00", "Z"),
        "totals": totals,
        "by_flow_reason": [
            {"flow": flow, "reason": reason, "count": count}
            for (flow, reason), count in sorted(
                by_fr.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
    }


@router.get("/events")
def drift_events(
    window: WindowLiteral = Query("7d"),
    flow:    str | None = Query(None, description="legacy | agentic"),
    reason:  str | None = Query(None, description="e.g. refused_with_context"),
    handler: str | None = Query(None, description="e.g. faq | content"),
    limit:   int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_admin_user),
):
    """Recent drift events for the dashboard's "investigate" table.

    Filters compose AND-style; omit any to widen. Returns most-recent-
    first up to ``limit`` rows. Each row carries the full DriftContext
    metadata the orchestrator wrote, so the operator can read the
    original question + LLM response excerpt + which handler ran
    without joining to other tables.
    """
    since = datetime.now(timezone.utc) - _WINDOW_TO_DELTA[window]

    q = (db.query(AuditLog)
         .filter(AuditLog.action.like(_DRIFT_ACTION_PREFIX + "%"))
         .filter(AuditLog.created_at >= since))

    # `reason` is a SQL filter (cheap, hits the action index). `flow`
    # and `handler` live inside metadata JSON — done in Python after
    # the SQL fetch for portability. The reason filter narrows the
    # row set first so the JSON-side filter is cheap.
    if reason:
        # Accept either "refused_with_context" or
        # "assistant.drift.refused_with_context" — operator UI doesn't
        # need to know the action-prefix convention.
        bare = reason.removeprefix(_DRIFT_ACTION_PREFIX)
        q = q.filter(AuditLog.action == _DRIFT_ACTION_PREFIX + bare)

    rows = q.order_by(AuditLog.created_at.desc()).limit(limit * 4).all()
    # Python-side metadata filters. Over-fetched 4× to give the post-
    # filter a buffer; cap at `limit` after filtering.
    if flow or handler:
        filtered = []
        for r in rows:
            meta = r.metadata_json or {}
            if flow and meta.get("flow") != flow:
                continue
            if handler and meta.get("handler") != handler:
                continue
            filtered.append(r)
            if len(filtered) >= limit:
                break
        rows = filtered
    else:
        rows = rows[:limit]
    return {
        "events": [
            {
                "id":         r.id,
                "user_id":    r.user_id,
                "action":     r.action,
                "reason":     r.action.removeprefix(_DRIFT_ACTION_PREFIX),
                "metadata":   r.metadata_json or {},
                "created_at": r.created_at.isoformat().replace("+00:00", "Z")
                              if r.created_at else None,
            }
            for r in rows
        ],
        "count": len(rows),
        "limit": limit,
    }
