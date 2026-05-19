from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, JSON
from sqlalchemy.sql import func
from app.core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    # tenant_id added in migration 0023 (per contract Q1). Nullable in
    # the schema for backward compat with rows that predate the
    # migration; the application layer coerces NULL → 1 on read so
    # downstream code never has to handle the NULL case explicitly.
    # New rows always set this via audit_log() helper which defaults
    # to get_current_tenant_id().
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       index=True)
    action = Column(String(64), nullable=False, index=True)
    ip = Column(String(45))
    user_agent = Column(String(255))
    request_id = Column(String(36))
    metadata_json = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
