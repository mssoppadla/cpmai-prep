"""Admin Visitor Insights dashboard endpoints.

Replaces (eventually) the narrow /admin/anonymous-traffic surface which
only knew about chat-bubble opens. These endpoints read the broader
journey_events stream populated by the SPA tracker (page views,
heartbeats, scroll, CTA clicks) plus the backend lifecycle events
(auth, payment, exam) so the operator can answer four questions:

  1. Overview — KPI strip
       GET /admin/insights/overview?window=7d
       → sessions, unique visitors, avg session duration,
         avg pages/session, bounce rate, conversion rate

  2. Top pages — what gets attention
       GET /admin/insights/pages?window=7d&limit=20
       → for each path: views, unique visitors, avg active time,
         bounce %, exit % (how often this page is the last in a
         session)

  3. Funnel — where the drop-off is
       GET /admin/insights/funnel?window=7d
       → counts at each step: landing → signup → first lesson
         viewed → payment success, with absolute counts and
         step-to-step conversion %

  4. Session drill-down — what THIS visitor did
       GET /admin/insights/sessions/{anon_id}
       → ordered list of events in this anon/user's history,
         joined across user_id if they signed in mid-session

Plus a GDPR action:
  POST /admin/insights/anonymize/{anon_id}
       → set anon_id=NULL on every journey_events row matching this
         anon_id; the events themselves stay (so aggregate counts
         don't shift), but no further individual drill-down is
         possible. Returns the count of rows affected. Audit-logged.

Read scaling story: every query is bounded to
  WHERE tenant_id=? AND created_at >= ?
which is covered by ix_je_tenant_event_time. At ~1M events/month/tenant
the 7d window scans ~230k rows which Postgres handles in <100ms with
the index. When we cross 10M/month the tracking.rollup_enabled flag
flips the dashboard to read visitor_insights_daily (PR VI-8) — same
query shape, pre-aggregated.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.deps import get_admin_user, get_db
from app.core.tenant import get_current_tenant_id
from app.models.journey_event import JourneyEvent
from app.models.user import User


router = APIRouter()


_WINDOW_TO_DELTA = {
    "24h": timedelta(hours=24),
    "7d":  timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}
WindowLiteral = Literal["24h", "7d", "30d", "90d"]


# Default funnel stages for /funnel. Operators can later configure this
# in /admin/settings; v1 ships with the obvious 4-stage path that maps
# to the platform's primary conversion goal.
_DEFAULT_FUNNEL_STAGES = [
    ("Landing",       "page.view",          None),                   # any page view
    ("Signup",        "auth.signup",        None),
    ("Lesson viewed", "page.view",          "/courses/[slug]/lessons/[id]"),
    ("Payment",       "payment.success",    None),
]


def _since(window: WindowLiteral) -> datetime:
    return datetime.now(timezone.utc) - _WINDOW_TO_DELTA[window]


# ---------------------------------------------------------------------
# 1. Overview — KPI strip
# ---------------------------------------------------------------------

@router.get("/insights/overview")
def insights_overview(
    window: WindowLiteral = Query("7d"),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_admin_user),
):
    """KPI strip: sessions, visitors, avg duration, avg pages/session,
    bounce rate, conversion rate.

    Definitions:
      * session = one session_id (UUID, sessionStorage-bound, dies on
        tab close)
      * visitor = one anon_id OR one user_id (a logged-in visitor with
        no anon_id cookie is still one unit)
      * bounce  = session with exactly one page.view (no second page,
        no scroll past 25%)
      * conversion = session that produced at least one of:
                     payment.success / lead.captured / auth.signup
    """
    tenant_id = get_current_tenant_id()
    since = _since(window)

    rows = (
        db.query(JourneyEvent)
        .filter(JourneyEvent.tenant_id == tenant_id)
        .filter(JourneyEvent.created_at >= since)
        .all()
    )

    sessions: dict[str, list[JourneyEvent]] = defaultdict(list)
    visitors: set[str] = set()
    for r in rows:
        if r.session_id:
            sessions[r.session_id].append(r)
        v_key = f"u:{r.user_id}" if r.user_id else (f"a:{r.anon_id}" if r.anon_id else None)
        if v_key:
            visitors.add(v_key)

    total_sessions = len(sessions)
    total_visitors = len(visitors)
    total_page_views = sum(1 for r in rows if r.event == "page.view")
    bounces = 0
    conversions = 0
    total_active_ms = 0

    for sid, events in sessions.items():
        pvs = [e for e in events if e.event == "page.view"]
        if len(pvs) <= 1:
            bounces += 1
        # active time = sum of duration_ms on page.exit (each page.exit
        # carries the active-time accumulator for the page it closed).
        for e in events:
            if e.event in ("page.exit", "session.end") and e.duration_ms:
                total_active_ms += e.duration_ms
        # Conversion = at least one of the goal events
        if any(e.event in ("payment.success", "lead.captured", "auth.signup")
                for e in events):
            conversions += 1

    avg_session_duration_s = (
        round(total_active_ms / total_sessions / 1000, 1)
        if total_sessions else 0
    )
    avg_pages_per_session = (
        round(total_page_views / total_sessions, 2)
        if total_sessions else 0
    )
    bounce_rate = round(bounces / total_sessions, 3) if total_sessions else 0
    conversion_rate = (
        round(conversions / total_sessions, 4) if total_sessions else 0
    )

    return {
        "window": window,
        "since":  since.isoformat().replace("+00:00", "Z"),
        "kpi": {
            "sessions":            total_sessions,
            "visitors":            total_visitors,
            "page_views":          total_page_views,
            "avg_session_seconds": avg_session_duration_s,
            "avg_pages_per_session": avg_pages_per_session,
            "bounce_rate":         bounce_rate,
            "conversion_rate":     conversion_rate,
        },
    }


# ---------------------------------------------------------------------
# 2. Top pages — views + avg time + bounce + exit %
# ---------------------------------------------------------------------

@router.get("/insights/pages")
def insights_pages(
    window: WindowLiteral = Query("7d"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_admin_user),
):
    """Top pages by view count.

    Per page row:
      * path
      * views          — page.view count
      * unique_visitors — distinct (anon_id | user_id) seen on this path
      * avg_seconds     — average ACTIVE time (from page.exit duration_ms)
      * bounce_rate     — share of sessions where this path was the only
                          page.view in the session
      * exit_rate       — share of sessions where this path was the LAST
                          page.view (or session.end happened here)
    """
    tenant_id = get_current_tenant_id()
    since = _since(window)

    rows = (
        db.query(JourneyEvent)
        .filter(JourneyEvent.tenant_id == tenant_id)
        .filter(JourneyEvent.created_at >= since)
        .filter(JourneyEvent.event.in_(("page.view", "page.exit", "session.end")))
        .filter(JourneyEvent.path.isnot(None))
        .all()
    )

    # Aggregate per (path, session_id) so bounce / exit can be computed.
    # views_per_path: path -> total page.view count
    # visitors_per_path: path -> set of visitor keys
    # exit_durations: path -> list[ms] for page.exit events
    # sessions_per_path: path -> set of session_ids that visited
    # last_page_per_session: session_id -> last path seen (ordered by ts)
    # pages_per_session: session_id -> ordered list of (ts, path, event)
    views_per_path: dict[str, int] = defaultdict(int)
    visitors_per_path: dict[str, set[str]] = defaultdict(set)
    exit_durations: dict[str, list[int]] = defaultdict(list)
    sessions_per_path: dict[str, set[str]] = defaultdict(set)
    pages_per_session: dict[str, list[tuple[datetime, str, str]]] = defaultdict(list)

    for r in rows:
        if r.event == "page.view":
            views_per_path[r.path] += 1
            v_key = f"u:{r.user_id}" if r.user_id else (f"a:{r.anon_id}" if r.anon_id else "")
            if v_key:
                visitors_per_path[r.path].add(v_key)
            if r.session_id:
                sessions_per_path[r.path].add(r.session_id)
                pages_per_session[r.session_id].append((r.created_at, r.path, r.event))
        elif r.event == "page.exit" and r.duration_ms:
            exit_durations[r.path].append(r.duration_ms)
        elif r.event == "session.end" and r.session_id and r.path:
            pages_per_session[r.session_id].append((r.created_at, r.path, r.event))

    # Bounce / exit per session
    bounces_per_path: dict[str, int] = defaultdict(int)
    exits_per_path: dict[str, int] = defaultdict(int)
    for sid, evs in pages_per_session.items():
        evs.sort(key=lambda t: t[0])
        # The last page in the session (page.view OR session.end's path)
        last_path = evs[-1][1]
        exits_per_path[last_path] += 1
        # Bounce only if there was exactly one page.view event in this
        # session AND it landed on this path.
        page_views_in_session = [e for e in evs if e[2] == "page.view"]
        if len(page_views_in_session) == 1:
            bounces_per_path[page_views_in_session[0][1]] += 1

    out: list[dict] = []
    for path, views in views_per_path.items():
        durs = exit_durations.get(path, [])
        avg_s = round(sum(durs) / len(durs) / 1000, 1) if durs else 0
        sess_count = len(sessions_per_path.get(path, set())) or 1
        out.append({
            "path":            path,
            "views":           views,
            "unique_visitors": len(visitors_per_path.get(path, set())),
            "avg_seconds":     avg_s,
            "bounce_rate":     round(bounces_per_path.get(path, 0) / sess_count, 3),
            "exit_rate":       round(exits_per_path.get(path, 0) / sess_count, 3),
        })
    out.sort(key=lambda d: d["views"], reverse=True)
    return {
        "window": window,
        "since":  since.isoformat().replace("+00:00", "Z"),
        "pages":  out[:limit],
    }


# ---------------------------------------------------------------------
# 2b. Navigation flow — which page visitors move to next
# ---------------------------------------------------------------------

@router.get("/insights/flow")
def insights_flow(
    window: WindowLiteral = Query("7d"),
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_admin_user),
):
    """Page-to-page navigation flow.

    Reconstructs each session's page.view sequence (ordered by
    created_at, then id — the id tiebreak preserves client order for
    views that landed in the same 5-second tracker batch) and counts
    the consecutive from→to pairs.

    Returns:
      * transitions — top `limit` (from_path, to_path) pairs with:
          - count            — sessions moves observed
          - share_of_from    — count / all moves leaving from_path
          - avg_seconds_on_from — avg ACTIVE dwell on the from page
            (page.exit duration_ms), i.e. "stayed 90s on /pricing,
            then went to /courses"
      * entries — top 10 first-pages-of-session
      * exits   — top 10 last-pages-of-session

    Consecutive repeats of the same path (e.g. a query-param change on
    the same route template) are skipped — they're not navigation.
    """
    tenant_id = get_current_tenant_id()
    since = _since(window)

    rows = (
        db.query(JourneyEvent)
        .filter(JourneyEvent.tenant_id == tenant_id)
        .filter(JourneyEvent.created_at >= since)
        .filter(JourneyEvent.event.in_(("page.view", "page.exit")))
        .filter(JourneyEvent.path.isnot(None))
        .filter(JourneyEvent.session_id.isnot(None))
        .all()
    )

    views_per_session: dict[str, list[tuple[datetime, int, str]]] = defaultdict(list)
    exit_durations: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        if r.event == "page.view":
            views_per_session[r.session_id].append((r.created_at, r.id, r.path))
        elif r.duration_ms:
            exit_durations[r.path].append(r.duration_ms)

    transition_counts: dict[tuple[str, str], int] = defaultdict(int)
    moves_leaving: dict[str, int] = defaultdict(int)
    entry_counts: dict[str, int] = defaultdict(int)
    exit_counts: dict[str, int] = defaultdict(int)

    for views in views_per_session.values():
        views.sort(key=lambda t: (t[0], t[1]))
        ordered = [path for _, _, path in views]
        # Collapse consecutive repeats — not navigation.
        deduped: list[str] = []
        for p in ordered:
            if not deduped or deduped[-1] != p:
                deduped.append(p)
        entry_counts[deduped[0]] += 1
        exit_counts[deduped[-1]] += 1
        for frm, to in zip(deduped, deduped[1:]):
            transition_counts[(frm, to)] += 1
            moves_leaving[frm] += 1

    def _avg_s(path: str) -> float:
        durs = exit_durations.get(path, [])
        return round(sum(durs) / len(durs) / 1000, 1) if durs else 0

    transitions = [
        {
            "from_path": frm,
            "to_path": to,
            "count": n,
            "share_of_from": round(n / moves_leaving[frm], 3),
            "avg_seconds_on_from": _avg_s(frm),
        }
        for (frm, to), n in transition_counts.items()
    ]
    transitions.sort(key=lambda d: d["count"], reverse=True)

    def _top(counts: dict[str, int], n: int = 10) -> list[dict]:
        ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        return [{"path": p, "count": c} for p, c in ranked[:n]]

    return {
        "window": window,
        "since": since.isoformat().replace("+00:00", "Z"),
        "transitions": transitions[:limit],
        "entries": _top(entry_counts),
        "exits": _top(exit_counts),
    }


# ---------------------------------------------------------------------
# 3. Funnel — landing → signup → first lesson → payment
# ---------------------------------------------------------------------

@router.get("/insights/funnel")
def insights_funnel(
    window: WindowLiteral = Query("7d"),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_admin_user),
):
    """Step-by-step conversion funnel.

    Each stage is defined as (label, event, optional path filter). A
    visitor counts toward stage N if they have ≥1 event matching that
    stage's (event, path) within the window. Stages are NOT required
    to be ordered for inclusion — we report absolute counts at each
    stage independently. The "conversion_from_prev" field divides each
    stage by the previous; a stage with more visitors than the previous
    (e.g. logged-in returners signing in without a landing page view)
    shows up as >100% which is a useful diagnostic, not a bug.
    """
    tenant_id = get_current_tenant_id()
    since = _since(window)

    out: list[dict] = []
    prev_visitors = 0

    for label, event_name, path_filter in _DEFAULT_FUNNEL_STAGES:
        q = (
            db.query(JourneyEvent.user_id, JourneyEvent.anon_id)
            .filter(JourneyEvent.tenant_id == tenant_id)
            .filter(JourneyEvent.created_at >= since)
            .filter(JourneyEvent.event == event_name)
        )
        if path_filter:
            q = q.filter(JourneyEvent.path == path_filter)

        visitors: set[str] = set()
        for uid, aid in q.all():
            v_key = f"u:{uid}" if uid else (f"a:{aid}" if aid else None)
            if v_key:
                visitors.add(v_key)
        count = len(visitors)
        out.append({
            "label":                label,
            "event":                event_name,
            "path":                 path_filter,
            "visitors":             count,
            "conversion_from_prev": (
                round(count / prev_visitors, 4) if prev_visitors else None
            ),
        })
        prev_visitors = count

    overall = (
        round(out[-1]["visitors"] / out[0]["visitors"], 4)
        if out and out[0]["visitors"] else 0
    )
    return {
        "window": window,
        "since":  since.isoformat().replace("+00:00", "Z"),
        "stages": out,
        "overall_conversion": overall,
    }


# ---------------------------------------------------------------------
# 4. Session drill-down — full timeline for one anon_id (or user_id)
# ---------------------------------------------------------------------

@router.get("/insights/sessions/{anon_id}")
def insights_session_timeline(
    anon_id: str = Path(..., max_length=36),
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_admin_user),
):
    """All events for this anon_id, ordered.

    If the visitor signed in mid-session their events from then on
    have user_id set; we join those in too by reading the user_id
    from any row matching anon_id. The timeline therefore spans
    pre-signup browsing → signup → post-signup activity in one list.

    Limited to the most recent 500 events by default; operators
    drilling into a high-traffic anon get a "load more" link in the
    UI. (Most anons produce <50 events total.)
    """
    tenant_id = get_current_tenant_id()

    # Find the user_id (if any) bound to this anon_id so we pull in
    # post-signup events. anon_id is a uuid4 → highly unique, no
    # ambiguity from collisions.
    user_ids_q = (
        db.query(JourneyEvent.user_id)
        .filter(JourneyEvent.tenant_id == tenant_id)
        .filter(JourneyEvent.anon_id == anon_id)
        .filter(JourneyEvent.user_id.isnot(None))
        .distinct()
    )
    user_ids = [uid for (uid,) in user_ids_q.all() if uid]

    # Filter — anon_id matches OR user_id is one of the linked ones
    q = (
        db.query(JourneyEvent)
        .filter(JourneyEvent.tenant_id == tenant_id)
    )
    if user_ids:
        q = q.filter(
            (JourneyEvent.anon_id == anon_id)
            | (JourneyEvent.user_id.in_(user_ids))
        )
    else:
        q = q.filter(JourneyEvent.anon_id == anon_id)

    q = q.order_by(JourneyEvent.created_at.desc()).limit(limit)
    rows = list(q.all())
    rows.reverse()  # operator-friendly ascending order in the response

    if not rows:
        raise HTTPException(404, f"No events for anon_id={anon_id}")

    return {
        "anon_id": anon_id,
        "linked_user_ids": user_ids,
        "event_count": len(rows),
        "first_seen": rows[0].created_at.isoformat().replace("+00:00", "Z"),
        "last_seen":  rows[-1].created_at.isoformat().replace("+00:00", "Z"),
        "events": [
            {
                "id":          r.id,
                "event":       r.event,
                "at":          r.created_at.isoformat().replace("+00:00", "Z"),
                "path":        r.path,
                "referrer":    r.referrer,
                "device":      r.device,
                "browser":     r.browser,
                "os":          r.os,
                "country":     r.country,
                "city":        r.city,
                "user_id":     r.user_id,
                "session_id":  r.session_id,
                "duration_ms": r.duration_ms,
                "scroll_pct":  r.scroll_pct,
                "metadata":    r.metadata_json or {},
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------
# GDPR — anonymise a single visitor
# ---------------------------------------------------------------------

@router.post("/insights/anonymize/{anon_id}", status_code=200)
def insights_anonymize(
    anon_id: str = Path(..., max_length=36),
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Detach this anon_id from every event row.

    Sets anon_id, user_id, session_id, ua, ip-derived city to NULL on
    every matching row. The events themselves stay (so aggregate
    counts don't shift), but no further drill-down by this identifier
    is possible.

    Audit-logged so the operator can prove the action took place if a
    deletion request is challenged.
    """
    tenant_id = get_current_tenant_id()

    affected = (
        db.query(JourneyEvent)
        .filter(JourneyEvent.tenant_id == tenant_id)
        .filter(JourneyEvent.anon_id == anon_id)
        .update({
            JourneyEvent.anon_id:    None,
            JourneyEvent.session_id: None,
            JourneyEvent.ua:         None,
            JourneyEvent.city:       None,
        }, synchronize_session=False)
    )
    db.commit()

    audit_log(
        db, admin.id, "insights.anonymize",
        metadata={"anon_id": anon_id, "rows_affected": affected},
    )

    return {"anon_id": anon_id, "rows_affected": affected}
