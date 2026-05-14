"""Chat endpoint + HITL flag / reply notifications (in-app)."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.core.audit import audit_log
from app.core.deps import get_current_user, get_db, get_optional_user
from app.core.exceptions import NotFoundError
from app.core.limiter import limiter
from app.models.assistant_flagged_turn import AssistantFlaggedTurn
from app.models.assistant_log import AssistantLog
from app.models.user import User
from app.schemas.assistant import AssistantRequest, AssistantResponse
from app.services.assistant.orchestrator import AssistantOrchestrator
from app.services.assistant.guardrails import AssistantGuardrails
from app.services.geoip.ip_extraction import extract_client_ip
from app.services.geoip.lookup import lookup as geoip_lookup

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
# Anonymous-visitor intent tracking. Fired when an anonymous user opens
# the chat widget — they showed conversion intent but the panel they see
# is a "please sign in" CTA. Where did this unconverted traffic come
# from? This endpoint captures the geoip-enriched event so /admin/leads's
# Anonymous Traffic section can roll it up by country / day.
#
# Volume control: rate-limited per-IP so a stuck client looping the
# bubble can't flood audit_logs. The frontend also de-dupes per session
# (only fires once per page-load lifecycle).
# ---------------------------------------------------------------------------


class AnonEventIn(BaseModel):
    """Kind enum is open-ended on purpose — start with bubble_open
    today, may add page_view / cta_seen later as appetite for tracking
    grows. The kind goes into the audit_log action suffix so dashboard
    filters can subset cleanly without metadata-JSON parsing."""
    kind: str = Field(default="bubble_open", max_length=64,
                       description="What the anonymous user did "
                                   "(bubble_open, etc.)")


@router.post("/anon-event", status_code=204)
@limiter.limit("60/minute")
def anon_event(payload: AnonEventIn, request: Request,
                user: User | None = Depends(get_optional_user),
                db: Session = Depends(get_db)):
    """Record an anonymous-visitor interaction with the chat surface.

    No-op when the request is already authenticated — we only care about
    unconverted traffic here. Returns 204 either way so the frontend
    doesn't need to branch on the response.

    Writes one ``audit_logs`` row with:
      action      = "assistant.anon.{kind}"  (e.g. "assistant.anon.bubble_open")
      ip          = the extracted client IP (honoring trusted-proxy depth)
      user_id     = NULL (anonymous by definition)
      metadata    = {country, city, anon_id} — country/city from the
                    existing GeoIP service; anon_id from the cookie
                    middleware (groups events from the same browser
                    even across page loads)

    Failure modes — none take down the chat:
      * GeoIP lookup fails → country/city omitted, event still recorded
      * audit_log write fails → 204 returned anyway (operational
        intelligence is best-effort, not load-bearing)
    """
    # Short-circuit for authenticated users — they're not anonymous.
    # We still 204 (idempotent contract) so the frontend doesn't need
    # to know whether the user signed in mid-session.
    if user is not None:
        return

    anon_id = getattr(request.state, "anon_id", None)
    ip = extract_client_ip(request)

    country = city = None
    if ip:
        geo = geoip_lookup(ip)
        if geo:
            country = geo.country
            city = geo.city

    # Sanitise kind — only allow alphanumeric + underscore so the
    # action column stays clean and we don't end up with
    # "assistant.anon.foo; DROP TABLE..." style mischief from a
    # crafted client. Doesn't 400 on garbage — silently coerces.
    safe_kind = "".join(c for c in (payload.kind or "")
                         if c.isalnum() or c == "_") or "unknown"

    try:
        audit_log(
            db, None, f"assistant.anon.{safe_kind}",
            metadata={
                "anon_id":  anon_id,
                "country":  country,
                "city":     city,
                # ip is also in the audit_log.ip column — we omit it
                # from metadata to avoid duplicate storage. The
                # dashboard reads country/city from metadata and ip
                # from the column directly when an admin drills in.
            },
            ip=ip,
        )
    except Exception:
        # Operational intelligence is best-effort. A stuck DB or
        # malformed metadata shouldn't surface to the visitor.
        pass


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
