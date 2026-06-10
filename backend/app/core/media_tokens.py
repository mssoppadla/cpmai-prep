"""Signed, expiring, path-bound tokens for protected upload media.

Why this exists
---------------
``/uploads/*`` is served by the backend. CMS marketing **images** are
public, but lesson **videos** and attached **PDFs/docs** are paid media:
a raw, never-expiring ``/uploads/...`` URL (visible in devtools) could be
copied and shared with non-paying users. To close that, the ``/uploads``
handler in ``app/main.py`` serves non-image files ONLY when the request
carries a valid token minted here.

Design
------
* The token is a short-lived JWT (HS256, ``settings.SECRET_KEY`` — the
  same secret as auth tokens, so rotating it invalidates these too).
* It is **bound to the exact relative path** (``path`` claim): a token
  minted for video A cannot fetch video B. Tampering is impossible
  without the secret (HMAC).
* ``type="media"`` keeps these distinct from access/refresh auth tokens,
  so an access token can't be replayed as a media token and vice-versa.
* ``sub`` (user id, 0 for anonymous free-preview) is carried for audit
  only; entitlement is enforced at mint time by the resource endpoint
  (it only signs paths the caller is allowed to see).

The minting boundary is ``protected_media_url`` — call it wherever an
entitled API response would otherwise emit a raw non-image upload URL.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.core.config import settings
from app.core.security import JWT_ALGORITHM


# Extensions served publicly by the /uploads handler (CMS images,
# course/lesson thumbnails). Everything else is treated as protected
# media and requires a signed token. Keep this in sync with the
# allow-list in ``app/main.py``.
PUBLIC_IMAGE_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif", ".ico",
})

# Default token lifetime. Long enough to watch a long lecture with
# pauses without the <video> element's src going stale mid-playback;
# short enough that a leaked/shared link stops working the same day.
# (A page reload re-mints, so this is only the in-flight validity.)
DEFAULT_MEDIA_TTL_SECONDS = 6 * 60 * 60  # 6 hours

_UPLOADS_PREFIX = "/uploads/"


def is_public_image(path: str) -> bool:
    """True if ``path`` (a URL or filename) is a publicly-served image."""
    # Strip any query string before looking at the extension.
    clean = path.split("?", 1)[0].rsplit(".", 1)
    if len(clean) != 2:
        return False
    return ("." + clean[1].lower()) in PUBLIC_IMAGE_EXTENSIONS


def sign_media_token(rel_path: str, user_id: int,
                     ttl_seconds: int = DEFAULT_MEDIA_TTL_SECONDS) -> str:
    """Mint a media token bound to ``rel_path`` (relative to UPLOAD_ROOT,
    i.e. the part after ``/uploads/``).

    ``user_id`` is recorded in the ``sub`` claim for audit; pass 0 for
    anonymous (free-preview) access.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "type": "media",
        "path": rel_path,
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALGORITHM)


def verify_media_token(token: str) -> dict | None:
    """Decode + verify a media token. Returns the claims dict, or None if
    the token is invalid, expired, or not a media token.

    Never raises — the caller (a static-file handler) just maps None to
    a 404 so it can't be distinguished from a missing file.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY,
                             algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
    if payload.get("type") != "media":
        return None
    if not payload.get("path"):
        return None
    return payload


def _normalise_rel_path(raw_url: str) -> str | None:
    """Extract the UPLOAD_ROOT-relative path from a ``/uploads/...`` URL.

    Returns None for anything that isn't an internal uploads path.
    """
    if not raw_url or not raw_url.startswith(_UPLOADS_PREFIX):
        return None
    rel = raw_url[len(_UPLOADS_PREFIX):]
    # Drop any pre-existing query string / fragment.
    rel = rel.split("?", 1)[0].split("#", 1)[0]
    return rel or None


def protected_media_url(
    raw_url: str | None, user_id: int,
    ttl_seconds: int = DEFAULT_MEDIA_TTL_SECONDS,
) -> str | None:
    """Return a URL the frontend can use for ``raw_url``.

    * empty / None                  → returned unchanged
    * external (http/https)         → returned unchanged (YouTube, Vimeo…)
    * internal image                → returned unchanged (public mount)
    * internal non-image media      → ``/uploads/<path>?token=<signed>``

    This is the single mint boundary: call it wherever an *entitled*
    response would otherwise leak a raw paid-media URL.
    """
    if not raw_url:
        return raw_url
    if re.match(r"^https?://", raw_url, re.IGNORECASE):
        return raw_url
    rel = _normalise_rel_path(raw_url)
    if rel is None:
        # Not an uploads path (e.g. a relative blob name we don't manage).
        return raw_url
    if is_public_image(rel):
        return raw_url
    token = sign_media_token(rel, user_id, ttl_seconds)
    return f"{_UPLOADS_PREFIX}{rel}?token={token}"
