"""visitor_insights_daily — nightly rollup of journey_events.

Exists from migration 0032 onward but stays empty until the
tracking.rollup_enabled setting is flipped on (PR VI-8).

Grain: one row per (tenant_id, day, path, event). Path or event may be
NULL to denote "all":
  * path=NULL, event=NULL     → tenant-day totals (KPI strip)
  * path=NULL, event='page.view' → tenant-day page-view total
  * path='/courses', event='page.view' → per-page-per-day rollup

The dashboard endpoint reads through a helper that flips between live
aggregation (over journey_events) and this rollup based on the
tracking.rollup_enabled setting.
"""
from sqlalchemy import (
    BigInteger, Column, Date, DateTime, Integer, String, UniqueConstraint, Index,
)
from sqlalchemy.sql import func
from app.core.database import Base


class VisitorInsightsDaily(Base):
    __tablename__ = "visitor_insights_daily"
    __table_args__ = (
        UniqueConstraint("tenant_id", "day", "path", "event",
                          name="uq_vid_grain"),
        Index("ix_vid_tenant_day", "tenant_id", "day"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, nullable=False)
    day = Column(Date, nullable=False)
    path = Column(String(255))      # NULL = all-pages aggregate
    event = Column(String(96))      # NULL = all-events aggregate

    views = Column(Integer, nullable=False, server_default="0")
    unique_visitors = Column(Integer, nullable=False, server_default="0")
    unique_sessions = Column(Integer, nullable=False, server_default="0")
    total_duration_ms = Column(BigInteger, nullable=False, server_default="0")
    bounces = Column(Integer, nullable=False, server_default="0")

    created_at = Column(DateTime(timezone=True),
                         server_default=func.now(), nullable=False)
