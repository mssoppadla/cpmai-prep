"""Normalise paths so dashboard GROUP BY doesn't explode.

# Two sources of path data, two normalisation strategies

1. **SPA tracker (the common case).** The frontend's TrackerMount
   uses Next.js's ``useParams()`` to derive the route template
   client-side (e.g. ``/courses/[slug]`` from
   ``/courses/cpmai-foundation-2026``). That value is sent verbatim
   in the ``path`` field, so this module has NOTHING to do for
   page.view / page.heartbeat / page.exit events — they arrive
   pre-templated.

2. **Backend-emitted events** (auth.signup, payment.success, etc.)
   sometimes carry a raw URL the backend knows from the request
   (e.g. ``/api/v1/payments/verify`` or a referrer). For those, we
   strip query strings, strip fragments, and apply a generic
   "collapse likely-dynamic segments" fallback so a never-before-seen
   route doesn't shatter dashboard cardinality.

# The collapsing rule

A path segment is collapsed to ``[*]`` when it:
  * is purely numeric (likely an id), OR
  * is a UUID-looking string (32+ hex chars or contains dashes in
    UUID positions), OR
  * is 12+ characters AND contains at least one digit (likely a
    slug like ``cpmai-foundation-2026``)

This is intentionally conservative — we'd rather KEEP a real path
segment than collapse a meaningful one. The trade-off is that very
short slugs (e.g. ``/about``, ``/help``, ``/contact``) stay literal,
which is what operators want.

We deliberately do NOT maintain a registry of specific dynamic
routes (e.g. ``/courses/[slug]``). That registry would drift every
time a developer adds a route and forgets to update the list. The
client-side derivation is the source of truth; this fallback handles
the small set of backend-emitted events where the client wasn't
involved.
"""
from __future__ import annotations

import re


_MAX_LEN = 255

# Segment matches if any of these apply
_NUMERIC_ID = re.compile(r"^\d+$")
_UUID_LIKE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)
_HEX_HASH = re.compile(r"^[0-9a-f]{32,}$", re.I)
_SLUG_LIKE = re.compile(r"^[\w-]{12,}$")


def _looks_dynamic(segment: str) -> bool:
    """True if this path segment is almost certainly a per-row
    identifier rather than a stable route component."""
    if not segment:
        return False
    if _NUMERIC_ID.match(segment):
        return True
    if _UUID_LIKE.match(segment):
        return True
    if _HEX_HASH.match(segment):
        return True
    # Slug-like: 12+ chars AND contains a digit (catches
    # "cpmai-foundation-2026" but spares "introduction" and "about").
    if _SLUG_LIKE.match(segment) and any(c.isdigit() for c in segment):
        return True
    return False


def normalise(raw_path: str | None) -> str:
    """Return a dashboard-friendly path for ``raw_path``.

    * Pre-templated paths (already contain ``[`` in any segment) pass
      through untouched — the client-side derivation is the trusted
      source.
    * Strips query string + fragment.
    * Replaces each likely-dynamic segment with ``[*]``.
    * Returns ``/`` for falsy input so the dashboard never sees an
      empty path.
    """
    if not raw_path:
        return "/"
    # Strip query + fragment
    p = raw_path.split("?", 1)[0].split("#", 1)[0]
    if not p:
        return "/"
    if not p.startswith("/"):
        p = "/" + p

    # Trim trailing slash for consistency (except root)
    if len(p) > 1 and p.endswith("/"):
        p = p[:-1]

    # Fast path — client already gave us a template (e.g. /courses/[slug])
    if "[" in p:
        return p[:_MAX_LEN]

    # Generic collapse — protects against new routes the client
    # didn't template (e.g. backend referrer fields).
    segments = p.split("/")
    out = [
        "[*]" if _looks_dynamic(seg) else seg
        for seg in segments
    ]
    return ("/".join(out) or "/")[:_MAX_LEN]


# ---- referrer / UTM helpers ----------------------------------------

_PII_QUERY_KEYS = {"email", "phone", "token", "auth", "password", "otp"}


def strip_pii_query(url: str | None) -> str | None:
    """Drop any query params whose key looks like PII before storing
    the referrer.  We keep the host + path + non-PII params.

    The "looks like PII" check is conservative — better to drop a
    benign param than to capture an email by accident.
    """
    if not url:
        return None
    if "?" not in url:
        return url[:512]

    base, _, qs = url.partition("?")
    clean_parts: list[str] = []
    for chunk in qs.split("&"):
        if "=" not in chunk:
            clean_parts.append(chunk)
            continue
        k, _, _v = chunk.partition("=")
        if k.lower() in _PII_QUERY_KEYS:
            continue
        clean_parts.append(chunk)

    out = base + (("?" + "&".join(clean_parts)) if clean_parts else "")
    return out[:512]
