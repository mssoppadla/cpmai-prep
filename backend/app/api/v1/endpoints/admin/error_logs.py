"""Admin error-log dashboard reads — /admin/error-logs.

Windowed views over the client error feed (see endpoints/errors.py for
what gets ingested and why). The window is minutes-based and fully
user-configurable client-side (5m / 10m / 1h / 24h presets), so an
operator mid-incident can run an instant "what broke in the last 5
minutes" check instead of waiting on a fixed daily rollup. Admin-gated
by the router-level get_admin_user dependency.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.models.error_log import ErrorLog

router = APIRouter()

# 5 minutes to 30 days. The frontend presets sit inside this range.
_WINDOW = Query(default=60, ge=5, le=43_200,
                description="Look-back window in minutes.")


def _since(minutes: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)


@router.get("/summary")
def error_summary(minutes: int = _WINDOW, db: Session = Depends(get_db)):
    """Aggregates for the dashboard header: totals, affected users, and
    the top error types / failing paths inside the window."""
    since = _since(minutes)
    base = db.query(ErrorLog).filter(ErrorLog.created_at >= since)

    total = base.count()
    affected_users = (db.query(func.count(func.distinct(ErrorLog.user_id)))
                      .filter(ErrorLog.created_at >= since,
                              ErrorLog.user_id.isnot(None)).scalar() or 0)
    affected_anons = (db.query(func.count(func.distinct(ErrorLog.anon_id)))
                      .filter(ErrorLog.created_at >= since,
                              ErrorLog.anon_id.isnot(None)).scalar() or 0)
    by_source = (db.query(ErrorLog.source, func.count(ErrorLog.id))
                 .filter(ErrorLog.created_at >= since)
                 .group_by(ErrorLog.source).all())
    top_types = (db.query(ErrorLog.error_type, func.count(ErrorLog.id))
                 .filter(ErrorLog.created_at >= since)
                 .group_by(ErrorLog.error_type)
                 .order_by(func.count(ErrorLog.id).desc()).limit(10).all())
    top_paths = (db.query(ErrorLog.path, func.count(ErrorLog.id))
                 .filter(ErrorLog.created_at >= since,
                         ErrorLog.path.isnot(None))
                 .group_by(ErrorLog.path)
                 .order_by(func.count(ErrorLog.id).desc()).limit(10).all())
    return {
        "window_minutes": minutes,
        "since": since.isoformat(),
        "total": total,
        "affected_users": affected_users,
        "affected_anons": affected_anons,
        "by_source": [{"source": s, "count": c} for s, c in by_source],
        "top_types": [{"error_type": t, "count": c} for t, c in top_types],
        "top_paths": [{"path": p, "count": c} for p, c in top_paths],
    }


@router.get("")
def list_errors(
    minutes: int = _WINDOW,
    source: Optional[str] = Query(default=None),
    error_type: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Raw rows, newest first, for the dashboard table."""
    q = db.query(ErrorLog).filter(ErrorLog.created_at >= _since(minutes))
    if source:
        q = q.filter(ErrorLog.source == source)
    if error_type:
        q = q.filter(ErrorLog.error_type == error_type)
    total = q.count()
    rows = (q.order_by(ErrorLog.created_at.desc())
            .offset(offset).limit(limit).all())
    return {
        "total": total,
        "rows": [{
            "id": r.id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "source": r.source,
            "error_type": r.error_type,
            "status_code": r.status_code,
            "path": r.path,
            "method": r.method,
            "message": r.message,
            "user_id": r.user_id,
            "anon_id": r.anon_id,
            "user_agent": r.user_agent,
        } for r in rows],
    }
