"""Audit log helper. Imported wherever sensitive actions occur.

Writes to two places:
  1. audit_logs table (durable, queryable record of who did what)
  2. structured log stream (developers tail this in real time)

Multi-tenancy (per contract A-2, H-3):
  ``audit_log()`` accepts an optional ``tenant_id`` kwarg. When omitted,
  it defaults to ``get_current_tenant_id()`` (= 1 in Phase 1). All
  existing call sites continue to work without changes — the new
  parameter is keyword-only and optional.
"""
import structlog
from sqlalchemy.orm import Session

from app.core.tenant import get_current_tenant_id
from app.models.audit_log import AuditLog


_log = structlog.get_logger("audit")


def audit_log(db: Session, user_id: int | None, action: str,
              metadata: dict | None = None, *,
              ip: str | None = None, user_agent: str | None = None,
              request_id: str | None = None,
              tenant_id: int | None = None) -> None:
    """Write an audit log entry.

    Args:
        db: DB session
        user_id: actor user_id; None for system events
        action: dotted-prefix action name (e.g. "user.role_changed")
        metadata: arbitrary JSON for the event payload
        ip / user_agent / request_id: request context
        tenant_id: tenant scope (Phase 1: optional, defaults to
            ``get_current_tenant_id()`` = 1 = CPMAI). Phase 2: every
            caller should pass an explicit tenant_id.

    NB: model attribute is ``metadata_json`` (the DB column is named
    ``metadata`` via ``Column("metadata", ...)`` — ``metadata`` itself
    can't be a Python attribute on a SQLAlchemy DeclarativeBase since
    the name collides with the registry's metadata). Passing
    ``metadata=`` would be silently dropped here; use the actual
    Python attr name.
    """
    if tenant_id is None:
        tenant_id = get_current_tenant_id()
    db.add(AuditLog(
        user_id=user_id, action=action,
        tenant_id=tenant_id,
        ip=ip, user_agent=user_agent, request_id=request_id,
        metadata_json=metadata or {},
    ))
    db.commit()
    _log.info("audit", action=action, user_id=user_id,
              tenant_id=tenant_id, **(metadata or {}))
