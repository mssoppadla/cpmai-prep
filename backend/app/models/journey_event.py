"""journey_events — funnel + visitor-insights event log.

Two read patterns this model is shaped for:

  1. Per-visitor timeline drill-down.
     SELECT * FROM journey_events
      WHERE anon_id = ? OR user_id = ?
      ORDER BY created_at;
     Served by ix_je_anon_time / ix_je_user_time.

  2. Dashboard rollups by tenant + event + day.
     SELECT path, COUNT(*), SUM(duration_ms), COUNT(DISTINCT anon_id)
       FROM journey_events
      WHERE tenant_id=? AND event='page.view' AND created_at >= ?
      GROUP BY path;
     Served by ix_je_tenant_event_time / ix_je_tenant_path_time.

The "visitor-insights" columns (path, referrer, utm_*, ua, device,
browser, os, country, city, duration_ms, scroll_pct) are populated by
POST /api/v1/track from the SPA. The "funnel" columns (event, user_id,
anon_id, session_id, request_id, metadata_json) are populated by
backend tracking_service.emit_event() at auth / payment / exam
lifecycle points. Both streams land in the same table because the
question "what did this visitor do from landing → signup → payment?"
is one timeline query, not two.
"""
from sqlalchemy import Column, Integer, SmallInteger, String, DateTime, JSON, Index
from sqlalchemy.sql import func
from app.core.database import Base


class JourneyEvent(Base):
    __tablename__ = "journey_events"
    __table_args__ = (
        # Per-visitor timeline scans
        Index("ix_je_user_time", "user_id", "created_at"),
        Index("ix_je_anon_time", "anon_id", "created_at"),
        # Session timeline drill-down (one session = ordered list of events)
        Index("ix_je_session_time", "session_id", "created_at"),
        # Dashboard scans — kept here so model + migration stay in sync.
        # The migration also creates these; duplicating the names in the
        # model is the convention used elsewhere (e.g. Campaign).
        Index("ix_je_tenant_event_time", "tenant_id", "event", "created_at"),
        Index("ix_je_tenant_path_time",  "tenant_id", "path",  "created_at"),
    )

    id = Column(Integer, primary_key=True)
    # Tenant scoping (contract I-1). server_default 1 backfills existing
    # rows to the bootstrap tenant; tracker writes a real value going
    # forward.
    tenant_id = Column(Integer, server_default="1")

    # Discrete event name from the EVENTS whitelist in tracking_service.
    # Widened from VARCHAR(64) → 96 in migration 0032.
    event = Column(String(96), nullable=False)

    # Identity. user_id OR anon_id is always set; both may be set when a
    # browser signs in mid-session and we keep tracking the same anon_id
    # cookie for funnel continuity.
    user_id = Column(Integer, index=True)
    anon_id = Column(String(36), index=True)
    session_id = Column(String(36), index=True)
    request_id = Column(String(36))

    # Page + referrer context (page.view / scroll.depth / cta.click / etc.)
    path        = Column(String(255))
    referrer    = Column(String(512))
    utm_source  = Column(String(64))
    utm_medium  = Column(String(64))
    utm_campaign = Column(String(128))

    # Device fingerprint — parsed from UA server-side. Stored as discrete
    # columns (not metadata JSON) so dashboard GROUP BY is cheap.
    ua      = Column(String(256))
    device  = Column(String(16))   # desktop / mobile / tablet / bot
    browser = Column(String(24))
    os      = Column(String(24))

    # GeoIP — duplicated from audit_log convention so dashboard joins
    # are O(1). Both nullable; private/datacenter IPs won't resolve and
    # we surface those as "Unknown" rather than dropping.
    country = Column(String(2))
    city    = Column(String(80))

    # Event-specific numerics
    duration_ms = Column(Integer)        # page.exit / page.heartbeat active time
    scroll_pct  = Column(SmallInteger)   # scroll.depth bucket (25/50/75/100)

    # Free-form payload — kept for forward-compat (new tracker signals
    # land here first, then promote to a column if needed).
    metadata_json = Column("metadata", JSON, default=dict)

    created_at = Column(DateTime(timezone=True),
                         server_default=func.now(), index=True)
