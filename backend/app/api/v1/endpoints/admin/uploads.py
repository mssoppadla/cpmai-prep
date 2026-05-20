"""Admin file upload endpoint — stores files to local disk.

Used by:
  * BlockNote editor (image paste / drag-drop) for text-lesson content
  * Lesson editor's "Attached Files" picker
  * Video lesson editor's file picker

Storage layout:
  /app/uploads/{tenant_id}/{YYYY}/{MM}/{uuid}-{safe_filename}

Files are served back via FastAPI's StaticFiles mount at /uploads/* —
configured in app/main.py.

R2 swap (Phase 2): the file_object_key field on LessonFile + a couple
of env vars (R2_BUCKET, R2_ACCESS_KEY_ID, R2_SECRET) let the same
endpoint POST to S3-compatible storage. Until then, local disk works
for both dev AND single-VPS prod (the VPS deploy already mounts
/var/cpmai-uploads as a docker volume).

Security:
  * gated by ``get_admin_user`` at the parent router level
  * filename sanitised (alphanumerics + . _ - only; everything else
    replaced) — defeats path-traversal even though pathlib also rejects
  * mime-type check: only allows image / video / pdf / common doc
    types. Configurable via ALLOWED_UPLOAD_MIMES env later if needed.
  * 100MB per-file cap (FastAPI's UploadFile streams to disk so RAM is
    fine; the cap protects local disk + slow-link timeouts).

Audit:
  * One audit_log row per upload with the resulting URL + size.
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.deps import get_admin_user, get_db
from app.core.exceptions import ValidationError
from app.core.tenant import get_current_tenant_id
from app.models.user import User


router = APIRouter()


# 100 MB. Tune via env later if operators upload bigger videos.
MAX_UPLOAD_BYTES = 100 * 1024 * 1024

ALLOWED_MIMES = {
    # Images
    "image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp", "image/svg+xml",
    # Video (lessons + R2 fallback)
    "video/mp4", "video/webm", "video/quicktime",
    # Audio (for podcast-style lessons)
    "audio/mpeg", "audio/wav", "audio/ogg",
    # Docs (attached files for assignments)
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/msword", "application/vnd.ms-excel",
    "text/plain", "text/csv", "application/json",
    "application/zip",
}


# Base directory for uploaded files. Mounted at /uploads/* in main.py.
# Configurable via env so the VPS deploy can point at a docker volume.
UPLOAD_ROOT = Path(os.environ.get("UPLOAD_ROOT", "/app/uploads"))


_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]")


def _sanitise(filename: str) -> str:
    """Strip dangerous characters from a filename. Path traversal is
    impossible from this output (no slashes, no .. unless explicitly
    typed which becomes "_" after replacement)."""
    base = os.path.basename(filename or "upload")
    cleaned = _SAFE_FILENAME_RE.sub("_", base)
    # Avoid empty / dot-only names
    if not cleaned or all(c == "." for c in cleaned):
        return "upload"
    return cleaned[:128]   # keep paths readable


def _public_url(rel_path: Path) -> str:
    """Construct the URL the frontend can fetch from. ``rel_path`` is
    relative to UPLOAD_ROOT. The static mount in main.py exposes
    UPLOAD_ROOT at /uploads, so /uploads/{rel_path} is the URL.

    Note: this is a path; the frontend prepends its API origin. For
    cross-origin uploads (admin on cpmaiexamprep.com, file URL on
    api.cpmaiexamprep.com), we return an absolute URL using the
    request's host. For simplicity in this PR we return the relative
    path and let the frontend prepend NEXT_PUBLIC_API_URL's origin.
    """
    return "/uploads/" + str(rel_path).replace("\\", "/")


@router.post("")
async def upload_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Upload one file. Returns ``{url, filename, mime_type, size_bytes}``
    that the caller can plug into a LessonFile create payload OR a
    BlockNote image block."""
    if file.content_type not in ALLOWED_MIMES:
        raise ValidationError(
            f"Unsupported file type '{file.content_type}'. Allowed: "
            f"images, videos, audio, PDFs, common Office docs, csv, zip."
        )
    sanitised = _sanitise(file.filename or "upload")

    # Per-tenant + date-partitioned path; the uuid prefix prevents
    # collisions when two admins upload files with the same name on
    # the same day.
    now = datetime.now(timezone.utc)
    tenant_id = get_current_tenant_id()
    rel_dir = Path(str(tenant_id)) / f"{now.year:04d}" / f"{now.month:02d}"
    abs_dir = UPLOAD_ROOT / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)

    final_name = f"{uuid.uuid4().hex[:12]}-{sanitised}"
    rel_path = rel_dir / final_name
    abs_path = UPLOAD_ROOT / rel_path

    # Stream-read with a running tally so we abort early on oversize.
    size = 0
    with abs_path.open("wb") as out:
        while True:
            chunk = await file.read(64 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                out.close()
                abs_path.unlink(missing_ok=True)
                raise ValidationError(
                    f"File exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit."
                )
            out.write(chunk)

    url = _public_url(rel_path)
    audit_log(db, admin.id, "file.uploaded", {
        "filename": sanitised,
        "size_bytes": size,
        "mime_type": file.content_type,
        "url": url,
    })
    return {
        "url": url,
        "filename": sanitised,
        "mime_type": file.content_type,
        "size_bytes": size,
    }
