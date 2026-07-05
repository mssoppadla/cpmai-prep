"""Attachment resolution for lifecycle emails — URL → verified disk path.

Automations store attachments exactly as /admin/uploads returned them
({url, filename, mime_type, size_bytes}); at send time we translate the
``/uploads/...`` URL back into a path under UPLOAD_ROOT.

Security contract (docs/contracts/email-automation.md §9): a stored URL
is admin-authored DATA, not trusted input. Every path is resolved and
verified to stay inside UPLOAD_ROOT (rejects ``..``, absolute paths,
and symlink escapes) before a byte is read.

Total payload is capped at save time (15MB — see admin endpoint) and
re-checked here defensively, since SMTP relays commonly reject ~25MB.
"""
from __future__ import annotations

import os
from pathlib import Path

import structlog

log = structlog.get_logger("email.attachments")

MAX_TOTAL_BYTES = 15 * 1024 * 1024


def _upload_root() -> Path:
    # Resolved per-call (not import time) so tests can repoint the env.
    return Path(os.environ.get("UPLOAD_ROOT", "/app/uploads")).resolve()


def resolve_attachment_paths(
    attachments: list | None,
) -> tuple[list[dict], str | None]:
    """Map stored attachment entries to verified on-disk paths.

    Returns ``(resolved, error)`` where resolved entries are
    ``{path, filename, mime_type}``. Any missing/escaping/oversize file
    returns an error naming the file — the caller fails the send rather
    than quietly delivering a mail without its promised attachment.
    """
    resolved: list[dict] = []
    total = 0
    root = _upload_root()
    for att in (attachments or []):
        if not isinstance(att, dict):
            return [], "malformed attachment entry"
        url = str(att.get("url") or "")
        name = str(att.get("filename") or "attachment")
        if not url.startswith("/uploads/"):
            return [], f"{name}: not an /uploads/ URL"
        rel = url[len("/uploads/"):]
        try:
            path = (root / rel).resolve()
        except (OSError, ValueError):
            return [], f"{name}: unresolvable path"
        # Python 3.8-compatible containment check not needed (3.12), but
        # is_relative_to is the canonical symlink-escape guard here.
        if not path.is_relative_to(root):
            log.warning("email.attachment_escape_blocked", url=url)
            return [], f"{name}: path escapes upload root"
        if not path.is_file():
            return [], f"{name}: file missing on server"
        size = path.stat().st_size
        total += size
        if total > MAX_TOTAL_BYTES:
            return [], f"{name}: total attachments exceed 15MB"
        resolved.append({
            "path": str(path),
            "filename": name,
            "mime_type": str(att.get("mime_type")
                             or "application/octet-stream"),
        })
    return resolved, None


def total_size_ok(attachments: list | None) -> bool:
    """Save-time validation using the size_bytes the upload endpoint
    reported — cheap check before the admin persists an automation."""
    total = 0
    for att in (attachments or []):
        if isinstance(att, dict):
            try:
                total += int(att.get("size_bytes") or 0)
            except (TypeError, ValueError):
                return False
    return total <= MAX_TOTAL_BYTES
