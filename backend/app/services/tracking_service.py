"""Emit journey events for funnel analytics."""
from sqlalchemy.orm import Session
from app.models.journey_event import JourneyEvent

EVENTS = {
    "page.view", "auth.signup", "auth.login", "auth.logout",
    "payment.order_created", "payment.success", "payment.failed",
    "subscription.activated", "subscription.cancelled",
    "exam.started", "exam.submitted",
    "assistant.message_sent",
    "lead.captured",
}


def emit_event(db: Session, event: str, *,
               user_id: int | None = None, anon_id: str | None = None,
               session_id: str | None = None, request_id: str | None = None,
               metadata: dict | None = None) -> None:
    if event not in EVENTS:
        # Soft-fail: log but don't break the request
        return
    db.add(JourneyEvent(
        event=event, user_id=user_id, anon_id=anon_id,
        session_id=session_id, request_id=request_id,
        metadata_json=metadata or {},
    ))
    db.commit()
