"""Pydantic schemas for the CMS AI-assist endpoints."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ----------------------------------------------------- /admin/cms-ai/generate-page

class GeneratePageIn(BaseModel):
    """Free-form prompt the admin types into the AI assist panel."""
    prompt: str = Field(min_length=1, max_length=2000)


class GeneratePageOut(BaseModel):
    """Block list returned by the LLM, normalised to BlockNote shape.

    Each block is a JSON dict that BlockNote can render directly. We
    don't strongly type the inner shape here because the AI service
    can emit any of several block types (heading/paragraph/list); the
    frontend treats the array as opaque BlockNote data."""
    blocks: list[dict[str, Any]]


# ----------------------------------------------------- /admin/cms-ai/fill-block

# Mirror of ALLOWED_BLOCK_TYPES in services/cms/ai_blocks.py. Kept as a
# Literal so Pydantic rejects unknown types at the API boundary.
BlockType = Literal["paragraph", "heading", "bulletListItem", "numberedListItem"]


class FillBlockIn(BaseModel):
    block_type: BlockType
    context: str = Field(default="", max_length=4000)


class FillBlockOut(BaseModel):
    """Plain text the editor swaps into the empty block."""
    text: str


# ----------------------------------------------------- /admin/cms-ai/improve-block

ImproveTone = Literal["shorter", "longer", "friendlier", "formal", "grammar"]


class ImproveBlockIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    tone: ImproveTone


class ImproveBlockOut(BaseModel):
    text: str
