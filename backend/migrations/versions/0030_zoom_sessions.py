"""Phase 1 PR #7 follow-up: Zoom integration (sessions + recordings).

Two tables for the Zoom track of Phase 1 (originally PR #4/#5 in the
roadmap sequence). Both are additive; downgrades raise per contract M-2.

  zoom_sessions
    Persists a Zoom Meeting that admin scheduled via /admin/sessions.
    The actual zoom_meeting_id field is populated when the Zoom REST
    API call succeeds — if the admin saved a session WITHOUT Zoom
    credentials configured (the SDK Key + Secret live in settings_store
    per the existing payment-provider pattern), zoom_meeting_id stays
    NULL and the public /lms/sessions endpoint shows a "scheduled,
    awaiting publish" state. Once credentials are added and the admin
    clicks "Publish", we call the Zoom REST API and store the ID.

    host_config (JSONB) captures the admin's choices for each session:
      {
        "mute_on_entry": bool,
        "allow_self_unmute": bool,        # user can unmute their mic
        "allow_video_toggle": bool,       # user can turn webcam on/off
        "chat_mode": "open" | "admin_only" | "off",
        "screen_share_mode": "approval" | "all_users" | "host_only",
        "waiting_room": bool,
        "lock_after_start": bool,         # no new joiners after start
        "auto_record": bool
      }

    These map to Zoom Meeting Settings + are also enforced client-side
    in the Web SDK embed (Z-B1).

    course_id is OPTIONAL — sessions can be standalone (e.g., a
    one-off webinar not tied to a specific course) or linked to a
    course's curriculum (a live class as part of a course).

    Status field tracks lifecycle:
      "draft"      — admin created, zoom_meeting_id NULL
      "scheduled"  — Zoom REST API call succeeded, meeting ready
      "live"       — currently in progress (driven by webhook)
      "ended"      — meeting finished
      "cancelled"  — admin cancelled before start

  recordings
    Created when the Zoom webhook fires `recording.completed` for a
    session we know about. We download the MP4 from Zoom's signed URL,
    push it to either UPLOAD_ROOT/recordings/{session_id}/... (local
    disk for single-VPS prod) or R2 (Phase 2). file_object_key stays
    NULL until R2 swap; today file_url is the canonical pointer.

    duration_seconds + ready_at populated from the webhook payload.

Per contract:
  - I-1: tenant_id default 1 on both tables
  - M-1, M-2, M-3: additive only, downgrade NotImplementedError, single tx

Revision ID: 0030_zoom_sessions (15 chars ≤ 32 ✓).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0030_zoom_sessions"
down_revision = "0029_course_discussion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ────────────────────────── zoom_sessions ──────────────────────────
    op.create_table(
        "zoom_sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer,
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                  nullable=False, server_default="1"),
        # Optional course linkage — NULL = standalone webinar
        sa.Column("course_id", sa.Integer,
                  sa.ForeignKey("courses.id", ondelete="SET NULL"),
                  nullable=True, index=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("duration_minutes", sa.Integer, nullable=False, server_default="60"),
        # Populated AFTER successful Zoom REST API call. NULL = draft.
        sa.Column("zoom_meeting_id", sa.String(64), nullable=True, unique=True),
        # Stored separately because it's PII-adjacent (the meeting URL).
        # The frontend NEVER receives this — only the signed SDK token.
        sa.Column("zoom_join_url", sa.Text, nullable=True),
        sa.Column("zoom_start_url", sa.Text, nullable=True),
        # Lifecycle marker — see module docstring.
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        # Admin's per-session control choices. See module docstring for shape.
        sa.Column("host_config", postgresql.JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        # Audit trail
        sa.Column("created_by", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), onupdate=sa.func.now(),
                  nullable=False),
        # Soft-delete (per contract M-2 pattern)
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
    )
    op.create_index(
        "ix_zoom_sessions_tenant_scheduled",
        "zoom_sessions",
        ["tenant_id", "scheduled_at"],
    )
    op.create_index(
        "ix_zoom_sessions_status_live",
        "zoom_sessions",
        ["status", "scheduled_at"],
        postgresql_where=sa.text("status IN ('scheduled', 'live') AND is_deleted = false"),
    )

    # ────────────────────────── recordings ──────────────────────────
    op.create_table(
        "recordings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer,
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                  nullable=False, server_default="1"),
        sa.Column("zoom_session_id", sa.Integer,
                  sa.ForeignKey("zoom_sessions.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        # Canonical pointer to the archived MP4. For single-VPS prod this
        # is a relative path under UPLOAD_ROOT/recordings/... For Phase 2
        # R2 storage, file_object_key is populated and file_url becomes
        # a CDN-friendly path.
        sa.Column("file_url", sa.Text, nullable=False),
        sa.Column("file_object_key", sa.Text, nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger, nullable=True),
        sa.Column("duration_seconds", sa.Integer, nullable=True),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        # The Zoom recording UUID — useful for cross-referencing with the
        # Zoom dashboard if a recording goes missing.
        sa.Column("zoom_recording_uuid", sa.String(64), nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    raise NotImplementedError(
        "0030_zoom_sessions: downgrade is intentionally unimplemented. "
        "Dropping these tables would lose every scheduled session, "
        "host_config preference, and recording archive — the kind of "
        "data Phase 1's contract M-2 forbids automating away. To revert, "
        "write a forward migration that archives + exports the data first."
    )
