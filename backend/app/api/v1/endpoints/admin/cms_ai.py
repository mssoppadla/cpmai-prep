"""Admin CMS AI-assist endpoints.

Three operations the BlockNote editor calls into:

  * POST /admin/cms-ai/generate-page    → block list from free-form prompt
  * POST /admin/cms-ai/fill-block       → text content for an empty block
  * POST /admin/cms-ai/improve-block    → rewrite an existing block's text

All gated by ``get_admin_user`` at the router level. Every call writes
an audit-log row so we have a trail of AI-generated content (useful
later for review/moderation and for understanding cost attribution).
The audit row includes the operation name and a truncated prompt /
text payload — full content is not logged to keep audit_logs slim.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.deps import get_admin_user, get_db
from app.models.user import User
from app.schemas.cms_ai import (
    FillBlockIn, FillBlockOut,
    GeneratePageIn, GeneratePageOut,
    ImproveBlockIn, ImproveBlockOut,
)
from app.services.cms import ai_blocks

router = APIRouter()


def _truncate(s: str, limit: int = 200) -> str:
    """Keep audit metadata small. Full strings live in chat history /
    LLM provider logs already."""
    if len(s) <= limit:
        return s
    return s[:limit] + "…"


@router.post("/generate-page", response_model=GeneratePageOut)
def generate_page(
    payload: GeneratePageIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    blocks = ai_blocks.generate_page(payload.prompt)
    audit_log(
        db, admin.id, "cms_ai.generate_page",
        {"prompt_excerpt": _truncate(payload.prompt), "block_count": len(blocks)},
    )
    return GeneratePageOut(blocks=blocks)


@router.post("/fill-block", response_model=FillBlockOut)
def fill_block(
    payload: FillBlockIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    text = ai_blocks.fill_block(payload.block_type, payload.context)
    audit_log(
        db, admin.id, "cms_ai.fill_block",
        {"block_type": payload.block_type,
         "context_excerpt": _truncate(payload.context),
         "result_chars": len(text)},
    )
    return FillBlockOut(text=text)


@router.post("/improve-block", response_model=ImproveBlockOut)
def improve_block(
    payload: ImproveBlockIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    text = ai_blocks.improve_block(payload.text, payload.tone)
    audit_log(
        db, admin.id, "cms_ai.improve_block",
        {"tone": payload.tone,
         "input_chars": len(payload.text),
         "result_chars": len(text)},
    )
    return ImproveBlockOut(text=text)
