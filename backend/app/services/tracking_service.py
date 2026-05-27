"""Emit journey events for funnel + visitor-insights analytics.

Writes to two destinations:
  1. journey_events table (durable, queryable funnel + insights data)
  2. structured log stream (developers tail this in real time, same way
     as audit events). Lines carry the event name plus user_id, anon_id,
     session_id, request_id, and any metadata.

Together with audit_log() and the request middleware, the file at
backend/logs/app.jsonl now shows a chronologically-ordered timeline of
each visitor: anonymous request → page.view × N → signup → login →
exam started → exam submitted → payment success, etc. Grep one user's
journey by `user_id` or `anon_id`.

Two flavours of caller:
  * Backend lifecycle events — auth, payments, exam — pass user_id /
    anon_id and a free-form metadata dict. They don't fill the new
    visitor-insights columns (path, ua, device, …) because they don't
    represent a page interaction.
  * Frontend tracker via POST /api/v1/track — fills every column from
    the SPA event. The endpoint handler is what calls emit_event with
    path/ua/etc kwargs; this module just persists them.
"""
import structlog
from sqlalchemy.orm import Session
from app.models.journey_event import JourneyEvent


_log = structlog.get_logger("journey")


# Whitelist of recognised event names. Adding new events anywhere in
# the codebase requires adding the name here too — this guards against
# typos and unbounded cardinality (which would blow up GROUP BY queries
# on the dashboard).
EVENTS = {
    # Visitor insights — emitted by the SPA tracker
    "page.view",         # initial page render
    "page.heartbeat",    # 15s active-time ping (Page Visibility filtered)
    "page.exit",         # pagehide / route-change leaving this page
    "scroll.depth",      # crossed 25/50/75/100% bucket
    "cta.click",         # clicked element with data-track="cta:<name>"
    "session.start",     # first event in a new session
    "session.end",       # navigator.sendBeacon on tab close (best-effort)
    # Auth
    "auth.signup", "auth.login", "auth.logout",
    "auth.login.google", "auth.signup.google",
    # Payments + subscription
    "payment.order_created", "payment.success", "payment.failed",
    "subscription.activated", "subscription.cancelled",
    # Exam lifecycle
    "exam.viewed", "exam.started", "exam.submitted",
    # AI assistant
    "assistant.message_sent",
    # Marketing
    "lead.captured",
}


def emit_event(
    db: Session,
    event: str,
    *,
    # Identity
    user_id: int | None = None,
    anon_id: str | None = None,
    session_id: str | None = None,
    request_id: str | None = None,
    # Tenant scoping (contract I-1). Caller passes the resolved tenant_id
    # from get_current_tenant_id(). Default 1 keeps existing callers
    # working without touching every emit_event() call site.
    tenant_id: int | None = 1,
    # Visitor-insights columns. All optional — backend lifecycle events
    # leave these None, the SPA tracker fills them.
    path: str | None = None,
    referrer: str | None = None,
    utm_source: str | None = None,
    utm_medium: str | None = None,
    utm_campaign: str | None = None,
    ua: str | None = None,
    device: str | None = None,
    browser: str | None = None,
    os: str | None = None,
    country: str | None = None,
    city: str | None = None,
    duration_ms: int | None = None,
    scroll_pct: int | None = None,
    # Free-form payload
    metadata: dict | None = None,
) -> None:
    """Record a journey event.

    Soft-fail on unknown event names — never break a request because a
    typo crept into a tracking call. Unknown names still get logged at
    WARN level so they are visible.

    Soft-fail on DB write errors too — analytics is best-effort and must
    not surface to the visitor. We log the failure so ops can see it.
    """
    if event not in EVENTS:
        _log.warning("journey.unknown_event", event=event,
                     user_id=user_id, anon_id=anon_id)
        return

    # Defensive: cap path length so a pathologically long URL can't
    # bloat the table or break the VARCHAR cap. Same for ua/referrer.
    if path is not None and len(path) > 255:
        path = path[:255]
    if referrer is not None and len(referrer) > 512:
        referrer = referrer[:512]
    if ua is not None and len(ua) > 256:
        ua = ua[:256]

    try:
        db.add(JourneyEvent(
            event=event,
            user_id=user_id,
            anon_id=anon_id,
            session_id=session_id,
            request_id=request_id,
            tenant_id=tenant_id,
            path=path,
            referrer=referrer,
            utm_source=utm_source,
            utm_medium=utm_medium,
            utm_campaign=utm_campaign,
            ua=ua,
            device=device,
            browser=browser,
            os=os,
            country=country,
            city=city,
            duration_ms=duration_ms,
            scroll_pct=scroll_pct,
            metadata_json=metadata or {},
        ))
        db.commit()
    except Exception as exc:  # noqa: BLE001 — analytics is best-effort
        db.rollback()
        _log.warning("journey.write_failed", event=event,
                      err=str(exc), user_id=user_id, anon_id=anon_id)
        return

    # Mirror to the structured log file so a developer tailing
    # backend/logs/app.jsonl sees the journey in real time.
    #
    # Build the kwargs dict carefully — existing backend callers
    # (auth.login, payment.success, etc.) pass things like
    # metadata={"country": "IN"} which would collide with our
    # explicit `country=` kwarg below. The merge order is:
    #   1. start with structural fields (event_name, identity)
    #   2. layer in tracker-derived columns IF set (path, country, …)
    #   3. let user-supplied metadata override anything
    # That way the auth path keeps its hand-rolled country metadata
    # and the tracker path keeps the parsed columns.
    log_kwargs = {
        "event_name": event,
        "user_id":    user_id,
        "anon_id":    anon_id,
        "session_id": session_id,
    }
    if path is not None:    log_kwargs["path"]    = path
    if country is not None: log_kwargs["country"] = country
    if device is not None:  log_kwargs["device"]  = device
    if browser is not None: log_kwargs["browser"] = browser
    log_kwargs.update(metadata or {})
    _log.info("journey", **log_kwargs)
