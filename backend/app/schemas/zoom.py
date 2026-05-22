"""Pydantic v2 schemas for the Zoom integration.

In/Out schemas split:
  * ZoomSessionCreateIn / UpdateIn — admin write payloads
  * ZoomSessionAdminOut             — full admin-facing payload (incl.
                                      zoom_join_url / start_url which
                                      are NEVER exposed publicly)
  * ZoomSessionPublicOut            — what enrolled users see; redacts
                                      join URLs since the public flow
                                      goes through the signed SDK token
  * RecordingOut                    — playback metadata; signed URL is
                                      issued by a separate endpoint

The nested ``HostConfig`` is the typed shape of zoom_sessions.host_config
(JSONB in the DB). Validating the shape here means a malformed admin
payload gets rejected at the API edge, not when the SDK embed barfs at
runtime.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ──────────────────────────────────────────────────────────────────────
# Nested host_config — the admin's per-session control choices.
# Defaults are intentionally PERMISSIVE for learners (allow self-unmute,
# allow video toggle, open chat) so admin only flips what they need to
# constrain. Auto-record defaults ON because most paid sessions want
# recordings for the post-session catch-up.
# ──────────────────────────────────────────────────────────────────────
class HostConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mute_on_entry: bool = True
    """Mute every learner's mic on join. Reduces echo in the first 30
       seconds when stragglers join with mic open."""

    allow_self_unmute: bool = True
    """If False, only the host can unmute a learner — useful for
       lectures where the host wants to call on people. If True, the
       Zoom mic button works as expected."""

    allow_video_toggle: bool = True
    """If False, the camera button is disabled — learners cannot turn
       their webcam on. Useful for low-bandwidth lectures."""

    chat_mode: Literal["open", "admin_only", "off"] = "open"
    """  open       — everyone can chat, see everyone's messages
         admin_only — learners can only DM the host; no public chat
         off        — chat panel hidden entirely for learners
    """

    screen_share_mode: Literal["approval", "all_users", "host_only"] = "approval"
    """  approval   — learner requests, host approves before share starts
         all_users  — any learner can share without asking
         host_only  — only the host can share
    """

    waiting_room: bool = True
    """Hold learners in a waiting room until host admits them. Prevents
       accidental joiners (wrong meeting ID) from landing in the room."""

    lock_after_start: bool = False
    """When the host clicks 'Lock', no further joiners allowed (even
       with the right meeting ID). Useful for "exam" style sessions."""

    auto_record: bool = True
    """Auto-record to the cloud. The Zoom webhook fires
       `recording.completed` when the recording is processed; our
       webhook handler downloads + archives to UPLOAD_ROOT/recordings."""


# ──────────────────────────────────────────────────────────────────────
# Write payloads
# ──────────────────────────────────────────────────────────────────────
class ZoomSessionCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = Field(default=None, max_length=4000)
    scheduled_at: datetime
    duration_minutes: int = Field(default=60, ge=10, le=480)
    course_id: Optional[int] = None
    host_config: HostConfig = Field(default_factory=HostConfig)


class ZoomSessionUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, min_length=2, max_length=255)
    description: Optional[str] = Field(default=None, max_length=4000)
    scheduled_at: Optional[datetime] = None
    duration_minutes: Optional[int] = Field(default=None, ge=10, le=480)
    course_id: Optional[int] = None
    host_config: Optional[HostConfig] = None
    status: Optional[Literal["draft", "scheduled", "live", "ended", "cancelled"]] = None


# ──────────────────────────────────────────────────────────────────────
# Read payloads
# ──────────────────────────────────────────────────────────────────────
class ZoomSessionAdminOut(BaseModel):
    """Full admin view. Includes zoom_join_url + zoom_start_url which
    are operationally useful for debugging but MUST NEVER leak to the
    public payload. The frontend admin renders these in a copy-to-
    clipboard box."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    course_id: Optional[int]
    title: str
    description: Optional[str]
    scheduled_at: datetime
    duration_minutes: int
    zoom_meeting_id: Optional[str]
    zoom_join_url: Optional[str]
    zoom_start_url: Optional[str]
    status: str
    host_config: dict
    created_by: Optional[int]
    created_at: datetime
    updated_at: datetime


class ZoomSessionPublicOut(BaseModel):
    """What an enrolled learner sees on /sessions. Note the omitted
    URLs — public join is via the signed SDK token endpoint, never via
    a raw Zoom join URL (which would let the user share their join link
    with non-subscribers)."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: Optional[int]
    title: str
    description: Optional[str]
    scheduled_at: datetime
    duration_minutes: int
    status: str
    # Lite version of host_config — UI uses this to gate buttons,
    # so we surface only the user-affecting fields.
    host_config: dict


class ZoomSDKTokenOut(BaseModel):
    """Returned by /lms/sessions/{id}/sdk-token. The Zoom Web SDK takes
    `signature` + `sdkKey` to bootstrap; both come from here. TTL is
    30 minutes — the user must click "Join live" within that window."""

    signature: str
    sdk_key: str
    meeting_number: str
    user_name: str
    role: int   # 0 = participant; 1 = host (always 0 for non-admin users)
    expires_at: datetime


# ──────────────────────────────────────────────────────────────────────
# Recordings
# ──────────────────────────────────────────────────────────────────────
class RecordingOut(BaseModel):
    """Playback metadata. The actual signed playback URL is issued by
    a SEPARATE endpoint per-request (so each playback is audit-logged
    independently). file_url here is the canonical storage path, not
    the playback URL."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    zoom_session_id: int
    duration_seconds: Optional[int]
    ready_at: Optional[datetime]
    created_at: datetime


class SignedRecordingPlaybackOut(BaseModel):
    """Returned by /lms/sessions/{id}/recording. The url is single-use
    + 1-hour TTL; calling the endpoint again issues a fresh signed URL
    (which is fine — each call is audit-logged)."""

    url: str
    expires_at: datetime
    duration_seconds: Optional[int]
