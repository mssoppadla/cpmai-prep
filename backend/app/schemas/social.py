"""Pydantic schemas for social automation campaigns + runs."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# Registered workflow types — kept here as the auth-of-truth for both
# API validation and the runner registry's lookup table.
WORKFLOW_TYPES = Literal[
    "weekly_content",       # OpenAI text → admin queue
    "session_reminder",     # 24h before zoom_session → text → queue
    "auto_clip",            # FFmpeg scene split of a video → queue
    "recording_published",  # zoom webhook → trailer clip → queue
]


# ─────────────────────────── Campaign ───────────────────────────

class CampaignCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=2, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)
    workflow_type: WORKFLOW_TYPES
    schedule_cron: Optional[str] = Field(
        default=None, max_length=120,
        description="5-field cron expression. Empty = manual-run only.",
    )
    config_json: dict[str, Any] = Field(default_factory=dict)
    active: bool = True


class CampaignUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)
    workflow_type: Optional[WORKFLOW_TYPES] = None
    schedule_cron: Optional[str] = Field(default=None, max_length=120)
    config_json: Optional[dict[str, Any]] = None
    active: Optional[bool] = None


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    name: str
    description: Optional[str]
    workflow_type: str
    schedule_cron: Optional[str]
    config_json: dict[str, Any]
    active: bool
    created_by: Optional[int]
    created_at: datetime
    updated_at: datetime


# ─────────────────────────── CampaignRun ───────────────────────────

class CampaignRunOut(BaseModel):
    """Admin view of a run. Used by /admin/social-queue."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    campaign_id: int
    started_at: datetime
    finished_at: Optional[datetime]
    status: str
    generated_content: Optional[str]
    posted_at: Optional[datetime]
    posted_to_platforms: list[dict[str, Any]]
    error: Optional[str]


class MarkPostedIn(BaseModel):
    """Admin marks a run as posted manually. Records WHICH platform +
    a URL to the post (so we can deep-link from the queue UI)."""
    model_config = ConfigDict(extra="forbid")

    platform: str = Field(..., min_length=1, max_length=64,
                          description="e.g. linkedin, youtube, instagram, twitter")
    url: Optional[str] = Field(default=None, max_length=2000)


class WorkflowMetaOut(BaseModel):
    """Describes a registered workflow for the admin form. Returned by
    GET /admin/campaigns/workflows so the UI can render correct
    config_json fields per workflow_type without hardcoding the list."""

    workflow_type: str
    label: str
    description: str
    config_schema: dict[str, Any]   # JSON-schema-ish shape for the UI
