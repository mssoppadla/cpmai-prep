"""Chat endpoint + HITL flag / reply notifications (in-app)."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.core.deps import get_current_user, get_db, get_optional_user
from app.core.exceptions import NotFoundError
from app.core.limiter import limiter
from app.models.assistant_flagged_turn import AssistantFlaggedTurn
from app.models.assistant_log import AssistantLog
from app.models.user import User
from app.schemas.assistant import AssistantRequest, AssistantResponse
from app.services.assistant.orchestrator import AssistantOrchestrator
from app.services.assistant.guardrails import AssistantGuardrails

router = APIRouter()
guardrails = AssistantGuardrails()


@router.post("/chat", response_model=AssistantResponse)
@limiter.limit("20/minute")
def chat(payload: AssistantRequest, request: Request, response: Response,
         user: User | None = Depends(get_optional_user),
         db: Session = Depends(get_db)):
    user_id = user.id if user else None
    anon_id = getattr(request.state, "anon_id", None)

    quota = guardrails.check_daily_limit(user_id=user_id, anon_id=anon_id)
    payload.user_id = user_id
    payload.anon_id = anon_id

    result = AssistantOrchestrator(db).handle(payload, user)

    response.headers["X-Chat-Quota-Used"]      = str(quota["used"])
    response.headers["X-Chat-Quota-Limit"]     = str(quota["limit"])
    response.headers["X-Chat-Quota-Remaining"] = str(quota["remaining"])
    response.headers["X-Chat-Quota-Reset"]     = quota["reset_at_utc"]
    return result


# ---------------------------------------------------------------------------
# HITL — user-facing endpoints.
# ---------------------------------------------------------------------------


class FlagTurnIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class FlagTurnOut(BaseModel):
    id: int
    assistant_log_id: int
    flagged_at: datetime
    status: str  # "pending" | "replied" | "closed"


@router.post("/turns/{log_id}/flag", response_model=FlagTurnOut,
             status_code=201)
@limiter.limit("10/day")
def flag_turn(log_id: int, request: Request,
              payload: FlagTurnIn | None = None,
              user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    """User flags a chat turn as unhelpful.

    Rate-limited to 10/day per IP to discourage spam-flagging. Idempotent
    on the (log_id) — second flag returns the existing row instead of
    erroring, so the widget can be safely re-clicked.
    """
    log = db.get(AssistantLog, log_id)
    if not log or log.user_id != user.id:
        # Treat "not yours" the same as "doesn't exist" — no enumeration.
        raise NotFoundError("Chat turn not found.")

    existing = (db.query(AssistantFlaggedTurn)
                .filter_by(assistant_log_id=log_id).first())
    if existing:
        status = ("closed" if existing.seen_by_user_at
                  else ("replied" if existing.replied_at else "pending"))
        return FlagTurnOut(id=existing.id, assistant_log_id=log_id,
                           flagged_at=existing.flagged_at, status=status)

    row = AssistantFlaggedTurn(
        assistant_log_id=log_id, user_id=user.id,
        flag_note=(payload.note.strip() if payload and payload.note else None),
    )
    db.add(row); db.commit(); db.refresh(row)
    return FlagTurnOut(id=row.id, assistant_log_id=log_id,
                       flagged_at=row.flagged_at, status="pending")


class NotificationOut(BaseModel):
    id: int
    assistant_log_id: int
    original_message: str   # the user's question, redacted snippet
    original_reply: str     # the AI's preview
    admin_reply: str
    replied_at: datetime
    replied_by_name: str | None = None


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    """Unread admin replies for the chat widget's red-dot logic.

    Returns flagged turns where the admin has replied but the user hasn't
    yet acknowledged. Sorted newest-first so the widget can render the
    most recent reply at the top of the transcript.
    """
    rows = (db.query(AssistantFlaggedTurn)
            .filter(AssistantFlaggedTurn.user_id == user.id,
                    AssistantFlaggedTurn.replied_at.isnot(None),
                    AssistantFlaggedTurn.seen_by_user_at.is_(None))
            .order_by(AssistantFlaggedTurn.replied_at.desc())
            .all())
    out = []
    for r in rows:
        log = db.get(AssistantLog, r.assistant_log_id)
        replier = db.get(User, r.replied_by) if r.replied_by else None
        out.append(NotificationOut(
            id=r.id, assistant_log_id=r.assistant_log_id,
            original_message=log.redacted_input if log else "",
            original_reply=log.response_preview if log else "",
            admin_reply=r.admin_reply or "",
            replied_at=r.replied_at,
            replied_by_name=replier.name if replier else None,
        ))
    return out


@router.post("/notifications/{flag_id}/seen", status_code=204)
def mark_notification_seen(flag_id: int,
                           user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    """User confirms they've seen an admin reply — clears the red dot."""
    row = db.get(AssistantFlaggedTurn, flag_id)
    if not row or row.user_id != user.id:
        raise NotFoundError("Notification not found.")
    if row.seen_by_user_at is None:
        row.seen_by_user_at = datetime.now(timezone.utc)
        db.commit()
