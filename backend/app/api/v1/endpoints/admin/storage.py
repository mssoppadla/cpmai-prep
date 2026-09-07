"""/admin/storage — one dashboard for every uploaded file.

Lists every file under UPLOAD_ROOT with WHERE it is used (via
services/storage_scan — the 10-location link sweep), and drives the
trash-not-delete lifecycle:

  * trash    — server RE-VERIFIES each path is still unlinked at action
               time; linked/held/system paths are skipped and reported,
               never deleted. The file MOVES into UPLOAD_ROOT/.trash/.
  * restore  — file-only by default (back at its original path,
               status returns to unlinked); ``revert_lesson=True`` on a
               switched original also points the lesson back at it.
  * empty-trash — the ONLY operation that frees disk; requires the
               caller to echo the exact current byte total.

Candidates (re-compressed copies of existing uploads) are recorded
here too; deciding one either switches the lesson to the compressed
file (original → trash, restorable) or discards the candidate file.

Safety rails, in order of importance:
  1. links re-verified server-side per action (no stale-listing deletes)
  2. files younger than HOLD_HOURS are "held" — never bulk-trashable
  3. system paths (invoices/, recordings/, rag, .trash/) excluded
  4. path containment: every filesystem op resolves inside UPLOAD_ROOT
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.deps import get_admin_user, get_db
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.media_tokens import sign_media_token
from app.core.tenant import get_current_tenant_id
from app.models.lms import Lesson
from app.models.media import MediaCandidate, MediaTrash
from app.models.user import User
from app.services.storage_scan import (
    TRASH_DIRNAME, is_system_path, links_for_paths, scan_links,
)

router = APIRouter()
log = logging.getLogger(__name__)

UPLOAD_ROOT = Path(os.environ.get("UPLOAD_ROOT", "/app/uploads"))
# New uploads stay out of the deletable pool this long — an admin
# usually uploads first and attaches a few minutes later, and the gap
# must never read as "unlinked".
HOLD_HOURS = 24


# ============================================================ helpers

def _rel_of(url: str) -> str | None:
    """/uploads/a/b.mp4 → a/b.mp4 (None for non-upload URLs)."""
    if not url or not url.startswith("/uploads/"):
        return None
    return url[len("/uploads/"):].split("?", 1)[0].lstrip("/")


def _safe_abs(url: str) -> Path | None:
    """Absolute path for an uploads URL, verified INSIDE UPLOAD_ROOT."""
    rel = _rel_of(url)
    if not rel:
        return None
    try:
        p = (UPLOAD_ROOT / rel).resolve()
        p.relative_to(UPLOAD_ROOT.resolve())
    except (OSError, ValueError):
        return None
    return p


def _signed_url(url: str, admin_id: int) -> str:
    """Signed download/preview URL for ANY upload (incl. trash) — the
    admin router already gates callers, so unlike protected_media_url we
    sign images too (harmless) and trash paths (needed for
    download-before-empty)."""
    rel = _rel_of(url)
    if not rel:
        return url
    return f"/uploads/{rel}?token={sign_media_token(rel, admin_id)}"


def _walk_uploads(tenant_id: int) -> list[dict]:
    """Every file under UPLOAD_ROOT (excluding .trash), with size/mtime.
    Multi-tenant note: content uploads live under {tenant_id}/...;
    system dirs (invoices/, recordings/) are global and included so the
    dashboard accounts for ALL disk, categorized as system."""
    out: list[dict] = []
    root = UPLOAD_ROOT
    if not root.exists():
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != TRASH_DIRNAME]
        for name in filenames:
            p = Path(dirpath) / name
            try:
                rel = p.relative_to(root)
                st = p.stat()
            except (OSError, ValueError):
                continue
            url = "/uploads/" + str(rel).replace("\\", "/")
            # Other tenants' content is invisible here.
            first = str(rel).replace("\\", "/").split("/", 1)[0]
            if (not is_system_path(url) and first.isdigit()
                    and int(first) != tenant_id):
                continue
            out.append({
                "path": url, "name": name, "size_bytes": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
            })
    return out


_UUID_PREFIX_RE = re.compile(r"^[0-9a-f]{12}-")


def _display_name(name: str) -> str:
    """Strip the collision-avoidance uuid prefix for display."""
    return _UUID_PREFIX_RE.sub("", name)


def _classify(f: dict, links: list, now: datetime) -> str:
    if is_system_path(f["path"]):
        return "system"
    if links:
        return "linked"
    if now - f["mtime"] < timedelta(hours=HOLD_HOURS):
        return "held"
    return "unlinked"


def _candidate_info(db: Session, path: str, scan) -> dict | None:
    mc = (db.query(MediaCandidate)
          .filter(MediaCandidate.tenant_id == get_current_tenant_id(),
                  MediaCandidate.candidate_path == path,
                  MediaCandidate.status == "pending")
          .first())
    if not mc:
        return None
    parent_links = [r.to_dict() for r in scan.links_for(mc.parent_path)
                    if r.kind not in ("candidate", "candidate_parent")]
    savings = 0
    if mc.parent_size_bytes:
        savings = round(100 * (1 - mc.size_bytes / mc.parent_size_bytes))
    return {
        "id": mc.id, "parent_path": mc.parent_path,
        "parent_links": parent_links, "lesson_id": mc.lesson_id,
        "savings_pct": savings,
    }


def _file_out(db: Session, f: dict, scan, admin_id: int,
              now: datetime) -> dict:
    links = [r for r in scan.links_for(f["path"])
             if r.kind not in ("candidate", "candidate_parent")]
    cand = _candidate_info(db, f["path"], scan)
    status = "candidate" if cand else _classify(f, links, now)
    return {
        "path": f["path"], "name": _display_name(f["name"]),
        "size_bytes": f["size_bytes"],
        "mime": mimetypes.guess_type(f["name"])[0],
        "uploaded_at": f["mtime"].isoformat(),
        "status": status,
        "links": [r.to_dict() for r in links],
        "candidate": cand,
        "download_url": _signed_url(f["path"], admin_id),
    }


# ============================================================ read API

@router.get("/overview")
def storage_overview(db: Session = Depends(get_db),
                     admin: User = Depends(get_admin_user)):
    tid = get_current_tenant_id()
    now = datetime.now(timezone.utc)
    scan = scan_links(db)
    files = _walk_uploads(tid)

    counts = {"linked": 0, "unlinked": 0, "held": 0,
              "candidates": 0, "system": 0}
    sizes = {"linked": 0, "unlinked": 0, "held": 0,
             "candidates": 0, "system": 0}
    cand_paths = {mc.candidate_path for mc in db.query(MediaCandidate).filter(
        MediaCandidate.tenant_id == tid, MediaCandidate.status == "pending")}
    for f in files:
        links = [r for r in scan.links_for(f["path"])
                 if r.kind not in ("candidate", "candidate_parent")]
        s = "candidates" if f["path"] in cand_paths \
            else _classify(f, links, now)
        key = s if s in counts else "candidates"
        counts[key] += 1
        sizes[key] += f["size_bytes"]

    trash_rows = (db.query(MediaTrash)
                  .filter(MediaTrash.tenant_id == tid,
                          MediaTrash.restored_at.is_(None)).all())
    trash_bytes = sum(t.size_bytes for t in trash_rows)
    return {
        "disk_used_bytes": sum(f["size_bytes"] for f in files) + trash_bytes,
        "linked_bytes": sizes["linked"],
        "unlinked_bytes": sizes["unlinked"],
        "held_bytes": sizes["held"],
        "candidate_bytes": sizes["candidates"],
        "system_bytes": sizes["system"],
        "trash_bytes": trash_bytes,
        "counts": {**counts, "trash": len(trash_rows)},
    }


@router.get("/files")
def storage_files(
    status: str = Query("all"),
    q: str = Query(""),
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    tid = get_current_tenant_id()
    now = datetime.now(timezone.utc)
    scan = scan_links(db)
    rows = [_file_out(db, f, scan, admin.id, now)
            for f in _walk_uploads(tid)]
    if status != "all":
        want = {"unlinked": {"unlinked", "held"}}.get(status, {status})
        rows = [r for r in rows if r["status"] in want]
    if q:
        needle = q.lower()
        rows = [r for r in rows
                if needle in r["name"].lower() or needle in r["path"].lower()]
    rows.sort(key=lambda r: r["size_bytes"], reverse=True)
    return rows


@router.get("/file")
def storage_file(path: str = Query(...),
                 db: Session = Depends(get_db),
                 admin: User = Depends(get_admin_user)):
    abs_path = _safe_abs(path)
    if not abs_path or not abs_path.is_file():
        raise NotFoundError("File not found")
    st = abs_path.stat()
    f = {"path": path.split("?", 1)[0], "name": abs_path.name,
         "size_bytes": st.st_size,
         "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)}
    return _file_out(db, f, scan_links(db), admin.id,
                     datetime.now(timezone.utc))


# ============================================================ trash

class TrashIn(BaseModel):
    paths: list[str] = Field(..., min_length=1, max_length=500)


@router.post("/trash")
def trash_files(payload: TrashIn,
                db: Session = Depends(get_db),
                admin: User = Depends(get_admin_user)):
    """Move files to trash. Every path is RE-VERIFIED against a fresh
    link scan; anything linked / held / system / missing is skipped and
    reported. Files move to .trash/ — nothing is deleted here."""
    tid = get_current_tenant_id()
    now = datetime.now(timezone.utc)
    live_links = links_for_paths(db, payload.paths)

    trashed: list[str] = []
    skipped: list[dict] = []
    trash_dir = UPLOAD_ROOT / TRASH_DIRNAME
    trash_dir.mkdir(parents=True, exist_ok=True)

    for raw in payload.paths:
        path = raw.split("?", 1)[0]
        refs = [r for r in live_links.get(raw, [])
                if r.kind not in ("candidate", "candidate_parent")]
        cand_refs = [r for r in live_links.get(raw, [])
                     if r.kind in ("candidate", "candidate_parent")]
        abs_path = _safe_abs(path)
        if is_system_path(path):
            skipped.append({"path": path, "reason": "system"})
            continue
        if refs or cand_refs:
            skipped.append({"path": path, "reason": "linked",
                            "links": [r.to_dict() for r in refs + cand_refs]})
            continue
        if not abs_path or not abs_path.is_file():
            skipped.append({"path": path, "reason": "missing"})
            continue
        st = abs_path.stat()
        if now - datetime.fromtimestamp(st.st_mtime, tz=timezone.utc) \
                < timedelta(hours=HOLD_HOURS):
            skipped.append({"path": path, "reason": "held"})
            continue

        trash_name = f"{uuid.uuid4().hex[:12]}-{abs_path.name}"
        dest = trash_dir / trash_name
        abs_path.rename(dest)
        db.add(MediaTrash(
            tenant_id=tid, original_path=path,
            trash_path=f"/uploads/{TRASH_DIRNAME}/{trash_name}",
            size_bytes=st.st_size,
            mime=mimetypes.guess_type(abs_path.name)[0],
            last_link_summary=json.dumps([]),
            trashed_by=admin.id,
        ))
        trashed.append(path)

    db.flush()
    audit_log(db, admin.id, "storage.trash",
              {"trashed": trashed, "skipped": [s["path"] for s in skipped]})
    db.commit()
    return {"trashed": trashed, "skipped": skipped}


def move_url_to_trash(db: Session, url: str, admin_id: int,
                      link_summary: list[dict] | None = None) -> MediaTrash | None:
    """Internal helper for code paths that retire a file deliberately
    (keep-candidate switch, lesson-file delete): move it to trash with
    a link snapshot, bypassing the unlinked check — the CALLER is the
    one detaching it. Returns None if the URL isn't a managed upload."""
    path = url.split("?", 1)[0] if url else ""
    abs_path = _safe_abs(path)
    if not abs_path or not abs_path.is_file():
        return None
    trash_dir = UPLOAD_ROOT / TRASH_DIRNAME
    trash_dir.mkdir(parents=True, exist_ok=True)
    st = abs_path.stat()
    trash_name = f"{uuid.uuid4().hex[:12]}-{abs_path.name}"
    abs_path.rename(trash_dir / trash_name)
    row = MediaTrash(
        tenant_id=get_current_tenant_id(), original_path=path,
        trash_path=f"/uploads/{TRASH_DIRNAME}/{trash_name}",
        size_bytes=st.st_size,
        mime=mimetypes.guess_type(abs_path.name)[0],
        last_link_summary=json.dumps(link_summary or []),
        trashed_by=admin_id,
    )
    db.add(row)
    db.flush()
    return row


@router.get("/trash-items")
def list_trash(db: Session = Depends(get_db),
               admin: User = Depends(get_admin_user)):
    rows = (db.query(MediaTrash)
            .filter(MediaTrash.tenant_id == get_current_tenant_id(),
                    MediaTrash.restored_at.is_(None))
            .order_by(MediaTrash.trashed_at.desc()).all())
    out = []
    for t in rows:
        try:
            was_links = json.loads(t.last_link_summary or "[]")
        except ValueError:
            was_links = []
        # A trashed original whose candidate got kept can revert the
        # lesson — surfaced so the UI can label the restore button.
        kept = (db.query(MediaCandidate)
                .filter(MediaCandidate.parent_path == t.original_path,
                        MediaCandidate.status == "kept")
                .order_by(MediaCandidate.decided_at.desc()).first())
        trashed_by_email = None
        if t.trashed_by:
            u = db.query(User).filter(User.id == t.trashed_by).first()
            trashed_by_email = u.email if u else None
        out.append({
            "id": t.id, "name": _display_name(Path(t.original_path).name),
            "original_path": t.original_path,
            "size_bytes": t.size_bytes, "mime": t.mime,
            "was_links": was_links,
            "trashed_at": t.trashed_at.isoformat() if t.trashed_at else None,
            "trashed_by_email": trashed_by_email,
            "is_kept_candidate_original": bool(kept and kept.lesson_id),
            "revert_lesson_id": kept.lesson_id if kept else None,
            "download_url": _signed_url(t.trash_path, admin.id),
        })
    return out


class RestoreIn(BaseModel):
    trash_id: int
    revert_lesson: bool = False


@router.post("/restore")
def restore_file(payload: RestoreIn,
                 db: Session = Depends(get_db),
                 admin: User = Depends(get_admin_user)):
    """Restore is file-only by default: the file returns to its original
    path (fresh uuid sibling on collision) and shows as Unlinked — it
    never silently rewrites live content. ``revert_lesson=True`` (only
    offered for the original of a kept candidate) also points the lesson
    back at the original, IF the lesson still serves that candidate."""
    tid = get_current_tenant_id()
    t = (db.query(MediaTrash)
         .filter(MediaTrash.id == payload.trash_id,
                 MediaTrash.tenant_id == tid,
                 MediaTrash.restored_at.is_(None)).first())
    if not t:
        raise NotFoundError("Trash item not found")
    src = _safe_abs(t.trash_path)
    if not src or not src.is_file():
        raise NotFoundError("Trashed file is missing on disk")

    dest = _safe_abs(t.original_path)
    if dest is None:
        raise ValidationError("Original path is not restorable")
    notice = None
    if dest.exists():
        # Path collision — restore under a fresh uuid sibling.
        fresh = f"{uuid.uuid4().hex[:12]}-{_display_name(dest.name)}"
        dest = dest.parent / fresh
        restored_path = t.original_path.rsplit("/", 1)[0] + "/" + fresh
        notice = "Original path was occupied — restored under a new name."
    else:
        restored_path = t.original_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dest)
    t.restored_at = datetime.now(timezone.utc)

    reverted = False
    if payload.revert_lesson:
        kept = (db.query(MediaCandidate)
                .filter(MediaCandidate.parent_path == t.original_path,
                        MediaCandidate.status == "kept")
                .order_by(MediaCandidate.decided_at.desc()).first())
        lesson = (db.query(Lesson).filter(
            Lesson.id == kept.lesson_id, Lesson.tenant_id == tid,
            Lesson.is_deleted.is_(False)).first()) if kept and kept.lesson_id else None
        if lesson is None:
            notice = ("The lesson this belonged to no longer exists — "
                      "restored as Unlinked; reattach it from the upload "
                      "picker.")
        elif (lesson.video_url or "").split("?", 1)[0] != kept.candidate_path:
            notice = ("The lesson's video changed since the switch — "
                      "restored file-only; the lesson was not touched.")
        else:
            lesson.video_url = restored_path
            kept.status = "pending"   # candidate back to pending
            kept.decided_at = None
            reverted = True

    audit_log(db, admin.id, "storage.restore",
              {"trash_id": t.id, "restored_path": restored_path,
               "reverted_lesson": reverted})
    db.commit()
    return {"restored_path": restored_path, "reverted_lesson": reverted,
            "notice": notice}


class EmptyTrashIn(BaseModel):
    confirm_bytes: int


@router.post("/empty-trash")
def empty_trash(payload: EmptyTrashIn,
                db: Session = Depends(get_db),
                admin: User = Depends(get_admin_user)):
    """The one operation that frees disk. Refuses (409) unless the
    caller echoes the exact current trash byte total — a changed trash
    since page load must be re-confirmed."""
    tid = get_current_tenant_id()
    rows = (db.query(MediaTrash)
            .filter(MediaTrash.tenant_id == tid,
                    MediaTrash.restored_at.is_(None)).all())
    total = sum(t.size_bytes for t in rows)
    if payload.confirm_bytes != total:
        raise ConflictError(
            f"Trash changed: it now holds {total} bytes, not "
            f"{payload.confirm_bytes}. Refresh and confirm again.")
    freed = 0
    for t in rows:
        p = _safe_abs(t.trash_path)
        if p and p.is_file():
            try:
                p.unlink()
                freed += t.size_bytes
            except OSError as e:
                log.warning("empty-trash unlink %s failed: %s", p, e)
                continue
        db.delete(t)
    audit_log(db, admin.id, "storage.empty_trash",
              {"deleted": len(rows), "freed_bytes": freed})
    db.commit()
    return {"deleted": len(rows), "freed_bytes": freed}


# ============================================================ candidates

class CandidateIn(BaseModel):
    parent_path: str
    candidate_path: str
    lesson_id: int | None = None


@router.post("/candidates")
def create_candidate(payload: CandidateIn,
                     db: Session = Depends(get_db),
                     admin: User = Depends(get_admin_user)):
    """Record a finished re-compression job's output as a pending
    candidate. Called by the compression popup after it uploads the
    encoded file via /admin/uploads."""
    parent = _safe_abs(payload.parent_path)
    cand = _safe_abs(payload.candidate_path)
    if not parent or not parent.is_file():
        raise NotFoundError("Parent file not found")
    if not cand or not cand.is_file():
        raise NotFoundError("Candidate file not found")
    row = MediaCandidate(
        tenant_id=get_current_tenant_id(),
        parent_path=payload.parent_path.split("?", 1)[0],
        candidate_path=payload.candidate_path.split("?", 1)[0],
        lesson_id=payload.lesson_id,
        size_bytes=cand.stat().st_size,
        parent_size_bytes=parent.stat().st_size,
    )
    db.add(row)
    db.flush()
    audit_log(db, admin.id, "storage.candidate_created",
              {"id": row.id, "parent": row.parent_path,
               "candidate": row.candidate_path})
    db.commit()
    return {"id": row.id}


class DecideIn(BaseModel):
    action: str   # "keep" | "discard"


@router.post("/candidates/{candidate_id}/decide")
def decide_candidate(candidate_id: int, payload: DecideIn,
                     db: Session = Depends(get_db),
                     admin: User = Depends(get_admin_user)):
    """keep: the lesson flips to the compressed file and the original
    moves to trash (restorable → revert option). discard: the candidate
    file is deleted and the lesson is untouched. Nothing happens until
    this endpoint is called — candidates never auto-swap."""
    if payload.action not in ("keep", "discard"):
        raise ValidationError("action must be 'keep' or 'discard'")
    tid = get_current_tenant_id()
    mc = (db.query(MediaCandidate)
          .filter(MediaCandidate.id == candidate_id,
                  MediaCandidate.tenant_id == tid,
                  MediaCandidate.status == "pending").first())
    if not mc:
        raise NotFoundError("Pending candidate not found")

    now = datetime.now(timezone.utc)
    if payload.action == "discard":
        p = _safe_abs(mc.candidate_path)
        if p and p.is_file():
            p.unlink(missing_ok=True)
        mc.status, mc.decided_at, mc.decided_by = "discarded", now, admin.id
        audit_log(db, admin.id, "storage.candidate_discarded", {"id": mc.id})
        db.commit()
        return {"status": "discarded"}

    # keep — verify the lesson still serves the parent before switching.
    lesson = (db.query(Lesson)
              .filter(Lesson.id == mc.lesson_id, Lesson.tenant_id == tid,
                      Lesson.is_deleted.is_(False)).first()
              if mc.lesson_id else None)
    if not lesson:
        raise ConflictError(
            "The lesson this candidate belongs to no longer exists — "
            "discard the candidate or reattach manually.")
    if (lesson.video_url or "").split("?", 1)[0] != mc.parent_path:
        raise ConflictError(
            "The lesson's video changed since this candidate was created "
            "— refresh and re-compress if still wanted.")

    scan_refs = [r.to_dict() for r in scan_links(db).links_for(mc.parent_path)
                 if r.kind not in ("candidate", "candidate_parent")]
    lesson.video_url = mc.candidate_path
    mc.status, mc.decided_at, mc.decided_by = "kept", now, admin.id
    trash_row = move_url_to_trash(db, mc.parent_path, admin.id,
                                  link_summary=scan_refs)
    audit_log(db, admin.id, "storage.candidate_kept",
              {"id": mc.id, "lesson_id": lesson.id,
               "original_trashed": bool(trash_row)})
    db.commit()
    return {"status": "kept", "lesson_id": lesson.id,
            "original_trash_id": trash_row.id if trash_row else None}
