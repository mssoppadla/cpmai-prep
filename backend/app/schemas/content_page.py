"""Pydantic schemas for the CMS admin API.

Three flavours of payload:

  * ContentPageOut       — full record (admin GET/list/PATCH responses)
  * ContentPageCreateIn  — POST body: slug + title required, rest defaulted
  * ContentPageUpdateIn  — PATCH body: every field optional, partial update

The slug regex enforces "alphanum and dashes, no leading/trailing dash,
no consecutive dashes". This is the URL the public site will eventually
expose at /pages/{slug} (PR #6). Stricter than the DB column (which
allows anything up to 128 chars) because we have the freedom to be strict
at the API edge.

``blocks`` is typed as ``list[dict]`` — we don't validate block shapes
in Phase 1. BlockNote (client-side) is the source of truth for block
structure; the server treats it as opaque JSON. If garbage gets in, the
client renderer will show a placeholder for that block.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# Mirror of app.models.content_page.NAV_VISIBILITY_CHOICES, expressed
# as a Literal so Pydantic enforces it at the schema layer.
NavVisibility = Literal["always", "authenticated", "subscribed", "hidden"]

# Slug rules: 1-128 chars, lowercase alphanum + single dashes; no
# leading/trailing dash, no doubled dashes. Matches what public URLs
# tolerate without escaping.
SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


class ContentPageOut(BaseModel):
    """Full admin payload — what /admin/content-pages returns."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    slug: str
    title: str
    blocks: list[dict[str, Any]]
    nav_visibility: NavVisibility
    nav_label: Optional[str]
    nav_order: int
    is_published: bool
    is_deleted: bool
    deleted_at: Optional[datetime]
    deleted_by: Optional[int]
    created_by: Optional[int]
    created_at: datetime
    updated_at: datetime


class ContentPageCreateIn(BaseModel):
    """POST body — slug + title are required, everything else optional.

    ``blocks`` defaults to an empty list — pages are created blank and
    filled in via subsequent PATCH calls (or the editor in PR #5).
    """
    slug: str = Field(min_length=1, max_length=128, pattern=SLUG_PATTERN)
    title: str = Field(min_length=1, max_length=256)
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    nav_visibility: NavVisibility = "always"
    nav_label: Optional[str] = Field(default=None, max_length=64)
    nav_order: int = Field(default=100, ge=0, le=10000)
    is_published: bool = False


class ContentPageUpdateIn(BaseModel):
    """PATCH body — every field optional. Use ``exclude_unset=True``
    on ``model_dump()`` to apply only the keys the client sent."""
    slug: Optional[str] = Field(
        default=None, min_length=1, max_length=128, pattern=SLUG_PATTERN,
    )
    title: Optional[str] = Field(default=None, min_length=1, max_length=256)
    blocks: Optional[list[dict[str, Any]]] = None
    nav_visibility: Optional[NavVisibility] = None
    nav_label: Optional[str] = Field(default=None, max_length=64)
    nav_order: Optional[int] = Field(default=None, ge=0, le=10000)
    is_published: Optional[bool] = None
