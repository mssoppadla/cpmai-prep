"""Admin chat-history viewer.

Reads from the existing AssistantLog table (already captures every
chat turn with intent, provider, model, redacted I/O, tokens, cost).
This module just exposes admin-friendly queries on top — no new
storage.

Two views:
  - `GET /admin/chat-history/users` — list of users who have ever
    chatted, with turn count + last-active timestamp. The "recent
    activity" overview.
  - `GET /admin/chat-history/users/{user_id}` — per-user chronological
    transcript. Drill-in from the overview.

Logs are intentionally redacted (PII stripped, response_preview
truncated to 500 chars). Admin gets enough to triage but doesn't see
private detail the user hasn't escalated.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from app.core.deps import get_admin_user, get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.models.assistant_flagged_turn import AssistantFlaggedTurn
from app.models.assistant_log import AssistantLog
from app.models.user import User


class _AlreadyReplied(ConflictError):
    code = "already_replied"

router = APIRouter()


@router.get("/users")
def list_chat_users(db: Session = Depends(get_db),
                    admin: User = Depends(get_admin_user),
                    limit: int = Query(50, le=200), offset: int = 0):
    """One row per user who has chatted, with turn count + last-active.

    Sorted by last-active DESC so the operator sees the most recent
    activity first. Anonymous chats (user_id IS NULL) are grouped into
    a single synthetic 'anonymous' bucket — visible but unlinkable.
    """
    rows = (db.query(
        AssistantLog.user_id,
        func.count(AssistantLog.id).label("turns"),
        func.max(AssistantLog.created_at).label("last_active"),
        func.sum(AssistantLog.tokens_in).label("tokens_in"),
        func.sum(AssistantLog.tokens_out).label("tokens_out"),
        func.sum(AssistantLog.cost_usd).label("cost_usd"),
    )
    .group_by(AssistantLog.user_id)
    .order_by(desc(func.max(AssistantLog.created_at)))
    .offset(offset).limit(limit).all())

    # Bulk-fetch user rows for the non-null user_ids.
    user_ids = [r.user_id for r in rows if r.user_id is not None]
    users = ({u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}
             if user_ids else {})

    # Per-user flag counts so the operator can spot high-friction users at
    # a glance. One query → dict lookup; cheap even at 200-row pages.
    flag_counts: dict[int, int] = {}
    if user_ids:
        for uid, cnt in (db.query(
                AssistantFlaggedTurn.user_id,
                func.count(AssistantFlaggedTurn.id))
            .filter(AssistantFlaggedTurn.user_id.in_(user_ids))
            .group_by(AssistantFlaggedTurn.user_id).all()):
            flag_counts[uid] = cnt

    out = []
    for r in rows:
        if r.user_id is None:
            out.append({
                "user_id": None, "email": None, "name": "(anonymous)",
                "turns": r.turns, "flagged": 0,
                "last_active": r.last_active,
                "tokens_in": int(r.tokens_in or 0),
                "tokens_out": int(r.tokens_out or 0),
                "cost_usd": float(r.cost_usd or 0),
            })
            continue
        u = users.get(r.user_id)
        out.append({
            "user_id": r.user_id,
            "email": u.email if u else None,
            "name":  u.name  if u else None,
            "turns": r.turns,
            "flagged": flag_counts.get(r.user_id, 0),
            "last_active": r.last_active,
            "tokens_in": int(r.tokens_in or 0),
            "tokens_out": int(r.tokens_out or 0),
            "cost_usd": float(r.cost_usd or 0),
        })
    return {"users": out}


# ---------------------------------------------------------------------------
# HITL admin queue + reply endpoints.
# ---------------------------------------------------------------------------


@router.get("/flagged")
def list_flagged_turns(db: Session = Depends(get_db),
                       admin: User = Depends(get_admin_user),
                       include_replied: bool = Query(False),
                       limit: int = Query(50, le=200), offset: int = 0):
    """Admin queue: flagged turns awaiting reply.

    Oldest-first so users who flagged earliest get answered first.
    Set `include_replied=true` to see already-handled flags too (for
    audit / retrospective review).
    """
    q = db.query(AssistantFlaggedTurn)
    if not include_replied:
        q = q.filter(AssistantFlaggedTurn.replied_at.is_(None))
    rows = (q.order_by(AssistantFlaggedTurn.flagged_at.asc())
            .offset(offset).limit(limit).all())

    user_ids   = {r.user_id for r in rows if r.user_id is not None}
    replier_ids = {r.replied_by for r in rows if r.replied_by is not None}
    log_ids    = [r.assistant_log_id for r in rows]
    users = ({u.id: u for u in db.query(User).filter(
                  User.id.in_(user_ids | replier_ids)).all()}
             if (user_ids or replier_ids) else {})
    logs = ({l.id: l for l in db.query(AssistantLog).filter(
                AssistantLog.id.in_(log_ids)).all()}
            if log_ids else {})

    items = []
    for r in rows:
        u = users.get(r.user_id) if r.user_id else None
        rep = users.get(r.replied_by) if r.replied_by else None
        log = logs.get(r.assistant_log_id)
        items.append({
            "id": r.id,
            "assistant_log_id": r.assistant_log_id,
            "user": {"id": r.user_id,
                     "email": u.email if u else None,
                     "name":  u.name  if u else None},
            "original_message": log.redacted_input if log else "",
            "original_reply":   log.response_preview if log else "",
            "provider": log.provider if log else None,
            "model":    log.model    if log else None,
            "flag_note": r.flag_note,
            "flagged_at": r.flagged_at,
            "admin_reply": r.admin_reply,
            "replied_at": r.replied_at,
            "replied_by": {"id": r.replied_by,
                           "name": rep.name if rep else None,
                           "email": rep.email if rep else None}
                          if r.replied_by else None,
        })
    return {"items": items}


class AdminReplyIn(BaseModel):
    reply: str = Field(min_length=1, max_length=4000)


@router.post("/turns/{flag_id}/reply")
def admin_reply(flag_id: int,
                payload: AdminReplyIn = Body(...),
                db: Session = Depends(get_db),
                admin: User = Depends(get_admin_user)):
    """Admin posts a follow-up reply for a flagged turn.

    Once replied, the row stays in the DB but stops appearing in the
    default queue (filter is `replied_at IS NULL`). Re-replying is
    rejected — if you need to correct a reply, follow up via a new
    flag-reply cycle for now.
    """
    row = db.get(AssistantFlaggedTurn, flag_id)
    if not row:
        raise NotFoundError("Flagged turn not found.")
    if row.replied_at is not None:
        raise _AlreadyReplied("This turn has already been replied to.")

    row.admin_reply = payload.reply.strip()
    row.replied_at = datetime.now(timezone.utc)
    row.replied_by = admin.id
    db.commit()
    return {"id": row.id, "replied_at": row.replied_at}


@router.get("/users/{user_id}")
def user_chat_transcript(user_id: int,
                         db: Session = Depends(get_db),
                         admin: User = Depends(get_admin_user),
                         limit: int = Query(200, le=1000), offset: int = 0):
    """Chronological transcript for one user.

    Returns redacted input + response_preview as captured by the
    orchestrator. Admin sees enough to spot patterns / triage; raw
    user text is intentionally not stored full-fidelity (PII compliance).
    """
    u = db.get(User, user_id)
    rows = (db.query(AssistantLog)
            .filter(AssistantLog.user_id == user_id)
            .order_by(AssistantLog.created_at.asc())
            .offset(offset).limit(limit).all())
    return {
        "user": {
            "id": user_id,
            "email": u.email if u else None,
            "name":  u.name  if u else None,
        },
        "turns": [
            {
                "id": r.id,
                "created_at": r.created_at,
                "intent": r.intent,
                "intent_confidence": r.intent_confidence,
                "provider": r.provider,
                "model": r.model,
                "input": r.redacted_input,
                "response_preview": r.response_preview,
                "tokens_in":  r.tokens_in,
                "tokens_out": r.tokens_out,
                "cost_usd":   float(r.cost_usd) if r.cost_usd else 0.0,
            }
            for r in rows
        ],
    }
