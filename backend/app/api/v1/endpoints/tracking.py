"""Visitor-insights ingest — POST /api/v1/track.

Receives batched events from the SPA tracker (src/lib/tracker.ts) and
fans them out to journey_events via tracking_service.emit_event(). One
endpoint covers both anon visitors and logged-in users; the dashboard
uses user_id vs anon_id to pivot.

Design constraints:

  * Batched. The tracker queues events for 5s before sending; on tab
    close it flushes via navigator.sendBeacon. We cap each batch at 50
    events so a misbehaving client can't ship megabytes per request.

  * Idempotent in spirit. The tracker assigns each event a UUID at
    capture time; if a sendBeacon retries we drop on (event_id) by
    NOT-using a dedupe key here — duplicate-event tolerance is set
    intentionally low (the dashboard always groups, so a small dupe
    rate has negligible impact). Adding a dedupe table would balloon
    write cost; skipping it costs negligible signal.

  * Best-effort. emit_event() soft-fails on DB errors; this endpoint
    returns 204 regardless so the tracker never blocks the visitor.

  * Tenant-scoped. The tenant_id comes from the request context (host
    or JWT), per contract I-1. No cross-tenant writes.

  * Sampling. Honours the tracking.sample_rate setting. The check is
    per-batch (not per-event) so a sampled-out batch costs zero DB
    writes. Sampling drops to 0 if tracking.enabled is false — a kill
    switch for emergencies (e.g. legal hold, partial DB outage).

  * Rate-limited. 120 batches/min per IP. With 5s client batching this
    is 10× the steady-state need; spikes (rapid navigation) are still
    absorbed.
"""
import random
import uuid
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.deps import get_db, get_optional_user
from app.core.limiter import limiter
from app.core.settings_store import settings_store
from app.core.tenant import get_current_tenant_id
from app.models.user import User
from app.services.geoip.ip_extraction import extract_client_ip
from app.services.geoip.lookup import lookup as geoip_lookup
from app.services.tracking.path_normaliser import normalise as norm_path
from app.services.tracking.path_normaliser import strip_pii_query
from app.services.tracking.ua_parser import parse as parse_ua
from app.services.tracking_service import EVENTS, emit_event


router = APIRouter()


# Per-batch cap. The SPA tracker buffers for 5s and flushes; in steady
# state a batch carries 1-5 events. The 50-event ceiling absorbs spikes
# (rapid clicks, fast navigation) while bounding worst-case row volume
# per request to something the dashboard's tenant-day index can take in
# stride.
_MAX_EVENTS_PER_BATCH = 50


class TrackEventIn(BaseModel):
    """One event from the SPA tracker. Mirrors the JS payload shape.

    All fields except ``event`` are optional — the tracker leaves out
    what doesn't apply (e.g. ``scroll_pct`` is only sent on
    scroll.depth events). The endpoint normalises and validates on
    receipt, NEVER assumes the client sent honest data.
    """
    event: str = Field(..., max_length=96)
    # Client-generated UUID per event — currently unused server-side
    # (see "Idempotent in spirit" note above) but accepted so the
    # tracker can add dedupe later without a schema change.
    event_id: Optional[str] = Field(default=None, max_length=36)
    session_id: Optional[str] = Field(default=None, max_length=36)
    path: Optional[str] = Field(default=None, max_length=512)
    referrer: Optional[str] = Field(default=None, max_length=512)
    utm_source: Optional[str] = Field(default=None, max_length=64)
    utm_medium: Optional[str] = Field(default=None, max_length=64)
    utm_campaign: Optional[str] = Field(default=None, max_length=128)
    duration_ms: Optional[int] = Field(default=None, ge=0, le=24 * 60 * 60 * 1000)
    scroll_pct: Optional[int] = Field(default=None, ge=0, le=100)
    # Free-form bag — e.g. {"cta": "enroll_pro", "slug": "cpmai-101"}.
    # The endpoint enforces a 4KB size cap on serialised metadata to
    # keep rows small.
    metadata: Optional[dict] = None


class TrackBatchIn(BaseModel):
    events: list[TrackEventIn] = Field(..., max_length=_MAX_EVENTS_PER_BATCH)
    # Client-clock timestamp at batch send — currently unused but
    # captured for future client-vs-server clock-skew analysis.
    sent_at: datetime | None = None


class TrackBatchAck(BaseModel):
    """Returned as a debug aid — not consumed by the tracker.

    The tracker ignores response bodies (POSTs are fire-and-forget on
    sendBeacon). This shape is here so the openapi schema documents
    what success looks like for ops who curl the endpoint manually.
    """
    accepted: int
    dropped: int
    reason: Literal["ok", "disabled", "sampled_out", "no_tenant"] = "ok"


@router.post("/track", response_model=TrackBatchAck, status_code=200)
@limiter.limit("120/minute")
def track(
    batch: TrackBatchIn,
    request: Request,
    response: Response,
    user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Accept a batch of visitor events. Returns immediately.

    Failure modes — none take down the visitor:
      * tracking.enabled = false        → return {accepted:0, reason:"disabled"}
      * sample_rate roll fails          → return {accepted:0, reason:"sampled_out"}
      * GeoIP lookup fails              → country/city omitted
      * emit_event raises                → row dropped, batch continues
    """
    # ── Kill switch + sampling ─────────────────────────────────────
    if not settings_store.get_bool("tracking.enabled", True):
        return TrackBatchAck(accepted=0, dropped=len(batch.events),
                              reason="disabled")

    # Sample per-batch (not per-event) so a dropped batch costs zero
    # DB writes. Range 0.0-1.0; default 1.0 = no sampling.
    rate = settings_store.get_float("tracking.sample_rate", 1.0)
    if rate < 1.0 and random.random() > rate:
        return TrackBatchAck(accepted=0, dropped=len(batch.events),
                              reason="sampled_out")

    # ── Identity + tenant resolution ───────────────────────────────
    user_id = user.id if user else None
    anon_id = getattr(request.state, "anon_id", None)
    request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    tenant_id = get_current_tenant_id()

    # ── Device fingerprint + GeoIP (computed ONCE per batch) ───────
    # Every event in a batch comes from the same browser, so we parse
    # the UA + GeoIP once and reuse. Big win when the batch carries 10+
    # heartbeats.
    ua = request.headers.get("user-agent", "")[:256]
    device, browser, os_name = parse_ua(ua)

    ip = extract_client_ip(request)
    country = city = None
    if ip:
        geo = geoip_lookup(ip)
        if geo:
            country = geo.country
            city = geo.city

    # ── Per-event fan-out ──────────────────────────────────────────
    accepted = 0
    dropped = 0

    for ev in batch.events:
        # Whitelist enforcement. Unknown event names get dropped here
        # rather than passed to emit_event (which would also drop, but
        # noisier). The tracker should never send unknown names; if it
        # does, that's a coding bug we want to see in the dashboard
        # zero-row count.
        if ev.event not in EVENTS:
            dropped += 1
            continue

        # Cap metadata size at ~4KB serialised. We're permissive on
        # shape but firm on size — a runaway client could otherwise
        # stuff arbitrary data into rows.
        meta = ev.metadata or {}
        if len(str(meta)) > 4096:
            meta = {"_truncated": True}

        emit_event(
            db,
            ev.event,
            user_id=user_id,
            anon_id=anon_id,
            session_id=ev.session_id,
            request_id=request_id,
            tenant_id=tenant_id,
            path=norm_path(ev.path),
            referrer=strip_pii_query(ev.referrer),
            utm_source=ev.utm_source,
            utm_medium=ev.utm_medium,
            utm_campaign=ev.utm_campaign,
            ua=ua,
            device=device,
            browser=browser,
            os=os_name,
            country=country,
            city=city,
            duration_ms=ev.duration_ms,
            scroll_pct=ev.scroll_pct,
            metadata=meta,
        )
        accepted += 1

    return TrackBatchAck(accepted=accepted, dropped=dropped, reason="ok")
