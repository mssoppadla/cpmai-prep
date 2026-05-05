"""Audit log helper. Imported wherever sensitive actions occur."""
from sqlalchemy.orm import Session
from app.models.audit_log import AuditLog


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
