"""Admin Zoom session management endpoints.

Schedule, edit, publish (= push to Zoom REST API), cancel, and list
ZoomSession rows. Recordings list is here too — playback signing lives
on the PUBLIC endpoint (lms_public.py) because that's where the
enrolled-only gate applies.

All routes are gated by ``get_admin_user`` at the parent router level.
Every write emits an audit_log entry. Tenant scope is enforced via
``get_current_tenant_id()`` on every query (contract I-3 + I-4).

# Publish flow

When an admin creates a session, we save a "draft" row immediately —
title, scheduled time, duration, host_config. If Zoom credentials are
configured, the REST API call is invoked synchronously and the
resulting meeting_id + URLs are stored. If credentials are missing
(common during initial setup), the row stays in "draft" status and the
admin sees a clear "Configure Zoom in /admin/settings then click
Publish" CTA in the UI.

The separate POST /admin/sessions/{id}/publish endpoint retries the
Zoom API call for draft sessions. This pattern lets the admin draft
sessions BEFORE wiring Zoom, then publish them in bulk later.

# Update + delete

PATCH propagates field changes to Zoom (if zoom_meeting_id is set)
AND to our row. DELETE is SOFT — sets is_deleted = True, also tries
to delete from Zoom (404 on Zoom side is fine — meeting already gone).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.deps import get_admin_user, get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.core.tenant import get_current_tenant_id
from app.models.user import User
from app.models.zoom import ZoomSession, Recording
from app.schemas.zoom import (
    HostConfig,
    RecordingOut,
    ZoomSessionAdminOut,
    ZoomSessionCreateIn,
    ZoomSessionUpdateIn,
)
from app.services.zoom_integration import (
    ZoomApiError,
    ZoomNotConfigured,
    zoom_client,
)


router = APIRouter()


def _scope(db: Session):
    return db.query(ZoomSession).filter(
        ZoomSession.tenant_id == get_current_tenant_id(),
        ZoomSession.is_deleted.is_(False),
    )


def _publish_to_zoom(s: ZoomSession) -> None:
    """Push a draft session up to Zoom. Mutates s in place. Raises
    ZoomNotConfigured if credentials missing; the endpoint should
    translate that to a 422 with a clear UI message."""
    meeting = zoom_client.create_meeting(
        topic=s.title,
        start_time=s.scheduled_at,
        duration_minutes=s.duration_minutes,
        host_config=s.host_config or {},
        agenda=s.description,
    )
    s.zoom_meeting_id = meeting.meeting_id
    s.zoom_join_url = meeting.join_url
    s.zoom_start_url = meeting.start_url
    s.status = "scheduled"


# ──────────────────────────────────────────────────────────────────────
# Sessions CRUD
# ──────────────────────────────────────────────────────────────────────
@router.get("/sessions", response_model=list[ZoomSessionAdminOut])
def list_sessions(
    db: Session = Depends(get_db),
    course_id: int | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    q = _scope(db)
    if course_id is not None:
        q = q.filter(ZoomSession.course_id == course_id)
    if status is not None:
        q = q.filter(ZoomSession.status == status)
    return (q.order_by(ZoomSession.scheduled_at.desc())
              .offset(offset).limit(limit).all())


@router.get("/sessions/{session_id}", response_model=ZoomSessionAdminOut)
def get_session(session_id: int, db: Session = Depends(get_db)):
    s = _scope(db).filter(ZoomSession.id == session_id).first()
    if not s:
        raise NotFoundError("Session not found")
    return s


@router.post("/sessions", response_model=ZoomSessionAdminOut, status_code=201)
def create_session(
    payload: ZoomSessionCreateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    s = ZoomSession(
        tenant_id=get_current_tenant_id(),
        course_id=payload.course_id,
        title=payload.title,
        description=payload.description,
        scheduled_at=payload.scheduled_at,
        duration_minutes=payload.duration_minutes,
        host_config=payload.host_config.model_dump(),
        status="draft",
        created_by=admin.id,
    )
    db.add(s)

    # Best-effort: if Zoom is configured, publish immediately. If not,
    # leave as draft — admin can click "Publish" later after configuring.
    # Mutates `s` in place (sets zoom_meeting_id, status='scheduled');
    # commits below pick up the modifications regardless of the path.
    try:
        _publish_to_zoom(s)
    except ZoomNotConfigured:
        # Expected during initial setup. The UI shows the "Configure
        # Zoom" CTA based on status === "draft".
        pass
    except ZoomApiError as e:
        # Configured but the API call failed — surface to admin.
        db.rollback()
        raise ValidationError(
            f"Zoom rejected the meeting: {e.body!r}"
        ) from e

    db.commit()
    db.refresh(s)
    audit_log(db, admin.id, "zoom_session.created",
              {"id": s.id, "status": s.status,
               "zoom_meeting_id": s.zoom_meeting_id})
    return s


@router.post("/sessions/{session_id}/publish",
             response_model=ZoomSessionAdminOut)
def publish_session(
    session_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Retry the Zoom REST API call for a draft session. Idempotent
    on already-published sessions (returns them unchanged)."""
    s = _scope(db).filter(ZoomSession.id == session_id).first()
    if not s:
        raise NotFoundError("Session not found")
    if s.zoom_meeting_id:
        return s  # already published
    try:
        _publish_to_zoom(s)
    except ZoomNotConfigured as e:
        raise ValidationError(str(e)) from e
    except ZoomApiError as e:
        raise ValidationError(f"Zoom rejected the meeting: {e.body!r}") from e
    db.commit(); db.refresh(s)
    audit_log(db, admin.id, "zoom_session.published",
              {"id": s.id, "zoom_meeting_id": s.zoom_meeting_id})
    return s


@router.patch("/sessions/{session_id}", response_model=ZoomSessionAdminOut)
def update_session(
    session_id: int,
    payload: ZoomSessionUpdateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    s = _scope(db).filter(ZoomSession.id == session_id).first()
    if not s:
        raise NotFoundError("Session not found")
    updates = payload.model_dump(exclude_unset=True)
    if "host_config" in updates and updates["host_config"] is not None:
        # Pydantic gave us a HostConfig object — convert.
        if isinstance(updates["host_config"], HostConfig):
            updates["host_config"] = updates["host_config"].model_dump()

    for k, v in updates.items():
        setattr(s, k, v)
    db.flush()

    # If the session is already pushed to Zoom and the admin changed
    # something Zoom cares about, mirror it upstream. Title / start /
    # duration / host_config are the propagatable fields.
    if s.zoom_meeting_id and any(k in updates for k in (
        "title", "scheduled_at", "duration_minutes", "host_config",
    )):
        try:
            zoom_client.update_meeting(
                s.zoom_meeting_id,
                topic=s.title,
                start_time=s.scheduled_at,
                duration_minutes=s.duration_minutes,
                host_config=s.host_config or {},
            )
        except ZoomNotConfigured:
            # Edge case: session has a meeting_id but Zoom creds got
            # rotated/cleared since then. Local update still works;
            # admin sees a warning in the UI.
            pass
        except ZoomApiError as e:
            db.rollback()
            raise ValidationError(
                f"Zoom rejected the update: {e.body!r}"
            ) from e

    db.commit(); db.refresh(s)
    audit_log(db, admin.id, "zoom_session.updated",
              {"id": s.id, "changed": sorted(updates.keys())})
    return s


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(
    session_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    s = _scope(db).filter(ZoomSession.id == session_id).first()
    if not s:
        raise NotFoundError("Session not found")
    s.is_deleted = True
    s.deleted_at = datetime.now(timezone.utc)
    s.deleted_by = admin.id
    s.status = "cancelled"

    # Best-effort delete from Zoom. Fail soft — the local soft-delete
    # is the authoritative action; if Zoom is unreachable we'll have
    # an orphan meeting up there but the user can't see it (since the
    # session row is gone from our system).
    if s.zoom_meeting_id:
        try:
            zoom_client.delete_meeting(s.zoom_meeting_id)
        except (ZoomNotConfigured, ZoomApiError):
            pass

    db.commit()
    audit_log(db, admin.id, "zoom_session.deleted",
              {"id": s.id, "zoom_meeting_id": s.zoom_meeting_id})


# ──────────────────────────────────────────────────────────────────────
# Recordings (admin view)
# ──────────────────────────────────────────────────────────────────────
@router.get("/sessions/{session_id}/recordings",
            response_model=list[RecordingOut])
def list_recordings(session_id: int, db: Session = Depends(get_db)):
    """List all recordings archived for this session. Public playback
    signing lives on the LMS public router."""
    # Confirm the session exists + is in tenant scope.
    s = _scope(db).filter(ZoomSession.id == session_id).first()
    if not s:
        raise NotFoundError("Session not found")
    return (db.query(Recording)
              .filter(Recording.zoom_session_id == s.id,
                      Recording.tenant_id == get_current_tenant_id())
              .order_by(Recording.created_at.desc()).all())
