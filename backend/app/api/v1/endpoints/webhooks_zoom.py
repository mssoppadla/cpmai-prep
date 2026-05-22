"""Zoom webhook receiver.

Mounted at /api/v1/webhooks/zoom (registered in app/api/v1/router.py).

Zoom delivers a v2 webhook signature scheme that we verify against
the secret token in settings_store (zoom.webhook_secret_token). Bad
signatures get a 401 — no enumeration of internal state, just a
generic rejection.

Events we handle:

  endpoint.url_validation        Zoom sends this when first connecting
                                 the webhook. We return the expected
                                 SHA256-based response so Zoom marks the
                                 endpoint verified.

  recording.completed            The recording archive trigger. We:
                                   1. Find the local ZoomSession by
                                      `payload.object.id` (= Zoom
                                      meeting id, stored as string)
                                   2. Pull the recording_files list
                                   3. For each MP4 file, download +
                                      stream into UPLOAD_ROOT/recordings/
                                      {session_id}/{ts}-{file_id}.mp4
                                   4. Insert a Recording row pointing
                                      at the file

  meeting.started / meeting.ended  Update session status accordingly
                                  so /sessions list shows "live" when
                                  the meeting actually starts.

Note on inline downloads: Zoom's signed recording download URLs are
typically valid for 24 hours and Zoom expects you to download "soon".
Downloading INSIDE the webhook handler keeps the contract simple
(one request = data archived) at the cost of a longer-than-usual
webhook response time for big recordings. If that becomes an issue,
swap to a background queue (Celery/RQ); the Recording row insert
stays in this handler so the lookup contract is preserved.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.core.settings_store import settings_store
from app.models.zoom import Recording, ZoomSession
from app.services.zoom_integration import verify_webhook_signature


router = APIRouter()
log = structlog.get_logger("webhooks_zoom")


UPLOAD_ROOT = Path(os.environ.get("UPLOAD_ROOT", "/app/uploads"))


@router.post("/zoom")
async def zoom_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_zm_request_timestamp: str | None = Header(default=None),
    x_zm_signature: str | None = Header(default=None),
):
    """Zoom webhook receiver. Verify, then dispatch by event."""
    raw_body = await request.body()
    payload = await request.json()
    event = payload.get("event")

    # Signature check applies to ALL events EXCEPT the URL validation
    # handshake (which doesn't carry a signature because Zoom hasn't
    # yet received the secret-token response).
    if event != "endpoint.url_validation":
        if not x_zm_request_timestamp or not x_zm_signature:
            raise HTTPException(401, "missing zoom signature headers")
        if not verify_webhook_signature(
            raw_body, x_zm_request_timestamp, x_zm_signature,
        ):
            raise HTTPException(401, "invalid signature")

    # ─────────────────────────── url_validation ───────────────────────────
    if event == "endpoint.url_validation":
        # Zoom sends { event, payload: { plainToken } }. We respond with
        #   { plainToken, encryptedToken: HMAC_SHA256(secret, plainToken) }
        # to prove we hold the secret. Same secret used for the signature
        # scheme above.
        plain = payload.get("payload", {}).get("plainToken", "")
        secret = settings_store.get_str("zoom.webhook_secret_token", "")
        if not secret:
            log.warning("zoom.webhook_secret_token not configured")
            raise HTTPException(503, "webhook not configured")
        encrypted = hmac.new(secret.encode(), plain.encode(),
                             hashlib.sha256).hexdigest()
        return {"plainToken": plain, "encryptedToken": encrypted}

    # ─────────────────────────── recording.completed ──────────────────────
    if event == "recording.completed":
        return await _handle_recording_completed(payload, db)

    # ─────────────────────────── meeting.started / ended ──────────────────
    if event in ("meeting.started", "meeting.ended"):
        return _handle_meeting_status(payload, event, db)

    # Anything else: ACK so Zoom doesn't retry, but log so we know.
    log.info("zoom.webhook_unhandled_event", event=event)
    return Response(status_code=204)


# ──────────────────────────────────────────────────────────────────────
# Event handlers
# ──────────────────────────────────────────────────────────────────────
async def _handle_recording_completed(payload: dict, db: Session) -> Response:
    """Archive completed recording MP4s to UPLOAD_ROOT.

    Failure modes handled:
      * Local ZoomSession not found (stale meeting / cross-tenant) →
        log + ACK so Zoom doesn't retry forever
      * Zoom recording payload missing download URL → log + skip
      * Download fails (network blip) → log + return 500 so Zoom retries
      * File write fails (disk full) → return 500 so Zoom retries
    """
    obj = payload.get("payload", {}).get("object", {})
    meeting_id = str(obj.get("id", ""))
    if not meeting_id:
        log.warning("zoom.recording_no_meeting_id", payload=payload)
        return Response(status_code=204)

    session = db.query(ZoomSession).filter(
        ZoomSession.zoom_meeting_id == meeting_id,
        ZoomSession.is_deleted.is_(False),
    ).first()
    if not session:
        log.info("zoom.recording_unknown_meeting", meeting_id=meeting_id)
        return Response(status_code=204)

    # Zoom sends `download_token` to use as a Bearer for the download URL.
    download_token = payload.get("download_token") or obj.get("download_token", "")

    recording_files = obj.get("recording_files", []) or []
    archived = 0
    for rf in recording_files:
        # Only archive video MP4s; chat-transcript + audio-only files
        # we skip for now (operator can fetch from Zoom UI if needed).
        if rf.get("file_type", "").upper() != "MP4":
            continue
        if not rf.get("download_url"):
            continue
        # De-dupe — same recording_uuid means we already grabbed it.
        rec_uuid = rf.get("id") or rf.get("recording_uuid")
        if rec_uuid:
            existing = db.query(Recording).filter(
                Recording.zoom_recording_uuid == rec_uuid,
            ).first()
            if existing:
                continue

        try:
            file_url, size_bytes = await _download_to_uploads(
                rf["download_url"], session.id, download_token,
            )
        except Exception as e:  # noqa: BLE001 — broad on purpose, returns 500
            log.error("zoom.recording_download_failed",
                      meeting_id=meeting_id, error=str(e))
            raise HTTPException(500, "download failed; Zoom will retry")

        duration_seconds = None
        try:
            # Zoom sends `recording_start` + `recording_end` as ISO strings
            start = rf.get("recording_start")
            end = rf.get("recording_end")
            if start and end:
                duration_seconds = int(
                    (datetime.fromisoformat(end.replace("Z", "+00:00"))
                     - datetime.fromisoformat(start.replace("Z", "+00:00")))
                    .total_seconds()
                )
        except Exception:
            pass

        rec = Recording(
            tenant_id=session.tenant_id,
            zoom_session_id=session.id,
            file_url=file_url,
            file_size_bytes=size_bytes,
            duration_seconds=duration_seconds,
            ready_at=datetime.now(timezone.utc),
            zoom_recording_uuid=rec_uuid,
        )
        db.add(rec)
        archived += 1

    if archived > 0:
        session.status = "ended"
    db.commit()

    log.info("zoom.recording_archived",
             meeting_id=meeting_id, session_id=session.id, files=archived)
    return Response(status_code=204)


async def _download_to_uploads(
    url: str, session_id: int, download_token: str | None,
) -> tuple[str, int]:
    """Stream a Zoom recording into UPLOAD_ROOT/recordings/<session_id>/.

    Returns (relative_file_url, total_bytes). relative_file_url is the
    /uploads/... path that StaticFiles serves; the model column stores
    that exact string.
    """
    rel_dir = Path("recordings") / str(session_id)
    abs_dir = UPLOAD_ROOT / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex[:12]}.mp4"
    abs_path = abs_dir / filename

    headers = {}
    if download_token:
        headers["Authorization"] = f"Bearer {download_token}"

    total = 0
    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream("GET", url, headers=headers) as resp:
            resp.raise_for_status()
            with abs_path.open("wb") as out:
                async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                    total += len(chunk)
                    out.write(chunk)

    rel_url = f"/uploads/{rel_dir.as_posix()}/{filename}"
    return rel_url, total


def _handle_meeting_status(payload: dict, event: str, db: Session) -> Response:
    """meeting.started → status='live'; meeting.ended → status='ended'."""
    obj = payload.get("payload", {}).get("object", {})
    meeting_id = str(obj.get("id", ""))
    if not meeting_id:
        return Response(status_code=204)
    session = db.query(ZoomSession).filter(
        ZoomSession.zoom_meeting_id == meeting_id,
        ZoomSession.is_deleted.is_(False),
    ).first()
    if not session:
        return Response(status_code=204)

    session.status = "live" if event == "meeting.started" else "ended"
    db.commit()
    log.info("zoom.meeting_status",
             meeting_id=meeting_id, session_id=session.id, status=session.status)
    return Response(status_code=204)
