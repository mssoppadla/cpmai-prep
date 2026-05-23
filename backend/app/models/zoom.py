"""SQLAlchemy models for Zoom sessions + recordings.

Schema reference: backend/migrations/versions/0030_zoom_sessions.py

The two tables here are independent from the LMS Course/Lesson tables —
a zoom_session CAN be linked to a course (column course_id) but doesn't
have to be. Standalone webinars, AMA sessions, and one-off demo classes
all live in this table without needing a course shell around them.

When linked to a course, the session usually appears as a "Live class"
node in the course curriculum, alongside text/video/quiz lessons. The
relationship is intentionally loose (no FK from Lesson to ZoomSession)
because:

  - A single session can be referenced by multiple courses (rare but
    legitimate — e.g. a guest lecturer doing the same talk across
    cohorts)
  - Sessions and lesson scheduling have different lifecycles: a session
    has a real-world start time, a lesson is on-demand
"""
from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey, Integer,
    JSON, String, Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class ZoomSession(Base):
    """A scheduled Zoom Meeting.

    Lifecycle: draft → scheduled → live → ended (or cancelled).

    Draft state means the row exists in the DB but the Zoom REST API
    call hasn't been made yet — usually because admin saved a session
    before configuring Zoom credentials in ``/admin/settings``. The
    public ``/lms/sessions`` endpoint hides draft sessions; admin sees
    them in ``/admin/sessions``.
    """
    __tablename__ = "zoom_sessions"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer,
                       ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=False, default=1)

    # Optional course linkage — NULL = standalone webinar.
    course_id = Column(Integer,
                       ForeignKey("courses.id", ondelete="SET NULL"),
                       nullable=True, index=True)

    title = Column(String(255), nullable=False)
    description = Column(Text)
    scheduled_at = Column(DateTime(timezone=True), nullable=False, index=True)
    duration_minutes = Column(Integer, nullable=False, default=60)

    # Populated AFTER Zoom REST API call succeeds. NULL → "draft".
    zoom_meeting_id = Column(String(64), unique=True)
    # PII-ish — never sent to the public frontend. Admin sees it in
    # /admin/sessions for ops debugging.
    zoom_join_url = Column(Text)
    zoom_start_url = Column(Text)

    status = Column(String(16), nullable=False, default="draft")

    # Admin's per-session control choices. Schema documented in the
    # migration file. Defaults to {} so a session created via API
    # without explicit host_config still validates.
    # Generic JSON (renders as JSONB on Postgres, JSON1 on SQLite for
    # the test harness) — keeps both prod migrations and unit-test
    # SQLite metadata.create_all() happy.
    host_config = Column(JSON, nullable=False, default=dict)

    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now(),
                        nullable=False)

    is_deleted = Column(Boolean, nullable=False, default=False)
    deleted_at = Column(DateTime(timezone=True))
    deleted_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))

    # Backref to Recording rows. Cascade-delete because a session being
    # hard-removed (test-only path; prod uses soft-delete) should drop
    # its recording archive too.
    recordings = relationship(
        "Recording",
        back_populates="session",
        cascade="all, delete-orphan",
    )


class Recording(Base):
    """An archived recording of a finished ZoomSession.

    Created by the Zoom webhook handler (Z-B2) when Zoom emits
    ``recording.completed`` for a session we know about. The handler:
      1. Downloads the MP4 from Zoom's signed URL
      2. Stores it under UPLOAD_ROOT/recordings/{session_id}/... (or R2)
      3. Inserts this row

    Playback is via a 1-hour single-use signed URL, requested by the
    enrolled user from ``/lms/sessions/{id}/recording`` and audited.
    """
    __tablename__ = "recordings"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer,
                       ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=False, default=1)
    zoom_session_id = Column(Integer,
                             ForeignKey("zoom_sessions.id",
                                        ondelete="CASCADE"),
                             nullable=False, index=True)

    file_url = Column(Text, nullable=False)
    file_object_key = Column(Text)           # R2/S3 key, NULL for local disk
    file_size_bytes = Column(BigInteger)
    duration_seconds = Column(Integer)
    ready_at = Column(DateTime(timezone=True))

    zoom_recording_uuid = Column(String(64), unique=True)

    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)

    session = relationship("ZoomSession", back_populates="recordings")
