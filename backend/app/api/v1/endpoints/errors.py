"""Client error ingest — POST /api/v1/errors/report.

Browsers report what the server can never see in its own logs: requests
that DIED ON THE WIRE. A QUIC stall (ERR_QUIC_PROTOCOL_ERROR), a dropped
connection, or a DNS failure surfaces client-side as `TypeError: Failed
to fetch` while the backend logs nothing at all — which is exactly why
the 2026-08 incidents looked "healthy" from the server. This endpoint
closes that blind spot; /admin/error-logs reads it back in windowed
summaries.

Best-effort by design: the reporter is fire-and-forget, so a fully
offline client can't report. Treat volumes as a floor, not a census.
Rate-limited per IP; payload fields hard-capped so a misbehaving client
can't stuff the table.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.deps import get_db, get_optional_user
from app.core.limiter import limiter
from app.models.error_log import ErrorLog
from app.models.user import User
from app.services.geoip.ip_extraction import extract_client_ip

router = APIRouter()


class ErrorReportIn(BaseModel):
    source: str = Field(..., pattern="^(network|api|frontend)$")
    error_type: str = Field(..., min_length=1, max_length=64)
    message: str = Field(default="", max_length=2000)
    path: Optional[str] = Field(default=None, max_length=500)
    method: Optional[str] = Field(default=None, max_length=10)
    status_code: Optional[int] = Field(default=None, ge=100, le=599)
    metadata: Optional[dict] = None


@router.post("/errors/report", status_code=204)
@limiter.limit("30/minute")
def report_error(
    payload: ErrorReportIn,
    request: Request,
    user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Store one client-side error. Always 204 — the reporter never
    retries and the visitor is never blocked on this call."""
    meta = payload.metadata or {}
    if len(str(meta)) > 4096:
        meta = {"_truncated": True}
    db.add(ErrorLog(
        user_id=user.id if user else None,
        anon_id=(request.headers.get("X-Anon-Token") or None),
        source=payload.source,
        error_type=payload.error_type[:64],
        status_code=payload.status_code,
        path=payload.path,
        method=payload.method,
        message=payload.message[:2000] or None,
        user_agent=request.headers.get("user-agent", "")[:255] or None,
        ip=extract_client_ip(request),
        metadata_json=meta,
    ))
    db.commit()
