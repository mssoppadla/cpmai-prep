"""Client/network error reports — the raw feed behind /admin/error-logs.

One row per error a browser managed to report: fetch failures (QUIC
stalls, connection drops, DNS), HTTP 5xx responses, and uncaught JS
exceptions. Deliberately fire-and-forget on the client — a user who is
fully offline can't report, so this is a floor on real error volume,
not an exact count.
"""
from sqlalchemy import Column, Integer, String, DateTime, JSON, Text
from sqlalchemy.sql import func
from app.core.database import Base


class ErrorLog(Base):
    __tablename__ = "error_logs"
    id = Column(Integer, primary_key=True)
    # Whoever was signed in when the error fired; NULL for anonymous.
    # No FK: reports must survive user deletion (GDPR redaction keeps
    # aggregate error history intact).
    user_id = Column(Integer, index=True)
    anon_id = Column(String(64), index=True)
    # "network" (fetch never resolved), "api" (5xx response),
    # "frontend" (uncaught JS exception / unhandled rejection)
    source = Column(String(16), nullable=False, index=True)
    # Machine label, e.g. "FETCH_FAILED", "HTTP_502", "UNCAUGHT_EXCEPTION"
    error_type = Column(String(64), nullable=False, index=True)
    status_code = Column(Integer)
    # API path or page URL where it happened
    path = Column(String(500))
    method = Column(String(10))
    message = Column(Text)
    user_agent = Column(String(255))
    ip = Column(String(45))
    # AuditLog pattern: attribute renamed because `metadata` is reserved
    # by SQLAlchemy's Declarative API; the DB column keeps the plain name.
    metadata_json = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(),
                        index=True)
