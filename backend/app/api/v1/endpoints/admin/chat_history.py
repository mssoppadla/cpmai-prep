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
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from app.core.deps import get_admin_user, get_db
from app.models.assistant_log import AssistantLog
from app.models.user import User

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

    out = []
    for r in rows:
        if r.user_id is None:
            out.append({
                "user_id": None, "email": None, "name": "(anonymous)",
                "turns": r.turns,
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
            "last_active": r.last_active,
            "tokens_in": int(r.tokens_in or 0),
            "tokens_out": int(r.tokens_out or 0),
            "cost_usd": float(r.cost_usd or 0),
        })
    return {"users": out}


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
