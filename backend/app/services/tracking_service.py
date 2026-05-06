"""Emit journey events for funnel analytics.

Writes to two destinations:
  1. journey_events table (durable, queryable funnel data)
  2. structured log stream (developers tail this in real time, same way
     as audit events). Lines carry the event name plus user_id, anon_id,
     session_id, request_id, and any metadata.

Together with audit_log() and the request middleware, the file at
backend/logs/app.jsonl now shows a chronologically-ordered timeline of
each visitor: anonymous request -> signup -> login -> exam started ->
exam submitted, etc. Grep one user's journey by `user_id` or `anon_id`.
"""
import structlog
from sqlalchemy.orm import Session
from app.models.journey_event import JourneyEvent


_log = structlog.get_logger("journey")


# Whitelist of recognized event names. Adding new events anywhere in
# the codebase requires adding the name here too — this guards against
# typos and unbounded cardinality.
EVENTS = {
    "page.view",
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


def emit_event(db: Session, event: str, *,
               user_id: int | None = None, anon_id: str | None = None,
               session_id: str | None = None, request_id: str | None = None,
               metadata: dict | None = None) -> None:
    """Record a journey event.

    Soft-fail on unknown event names — never break a request because a
    typo crept into a tracking call. Unknown names still get logged at
    WARN level so they are visible.
    """
    if event not in EVENTS:
        _log.warning("journey.unknown_event", event=event,
                     user_id=user_id, anon_id=anon_id)
        return

    db.add(JourneyEvent(
        event=event, user_id=user_id, anon_id=anon_id,
        session_id=session_id, request_id=request_id,
        metadata_json=metadata or {},
    ))
    db.commit()

    # Mirror to the structured log file so a developer tailing
    # backend/logs/app.jsonl sees the journey in real time.
    _log.info(
        "journey",
        event_name=event,
        user_id=user_id, anon_id=anon_id, session_id=session_id,
        **(metadata or {}),
    )
