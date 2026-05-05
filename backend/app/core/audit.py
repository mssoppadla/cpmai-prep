"""Audit log helper. Imported wherever sensitive actions occur.

Writes to two places:
  1. audit_logs table (durable, queryable record of who did what)
  2. structured log stream (developers tail this in real time)
"""
import structlog
from sqlalchemy.orm import Session
from app.models.audit_log import AuditLog


_log = structlog.get_logger("audit")


def audit_log(db: Session, user_id: int | None, action: str,
              metadata: dict | None = None, *,
              ip: str | None = None, user_agent: str | None = None,
              request_id: str | None = None) -> None:
    db.add(AuditLog(
        user_id=user_id, action=action,
        ip=ip, user_agent=user_agent, request_id=request_id,
        metadata=metadata or {},
    ))
    db.commit()
    _log.info("audit", action=action, user_id=user_id, **(metadata or {}))
