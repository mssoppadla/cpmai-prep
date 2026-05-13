"""Admin endpoints for live-FX management.

Two endpoints:

  GET   /admin/pricing/fx-status        Current effective rates + last
                                        refresh timestamp + per-currency
                                        provenance. Drives the
                                        /admin/pricing dashboard.

  POST  /admin/pricing/fx-refresh-now   Trigger a Frankfurter pull on
                                        demand. Used by the admin's
                                        "Refresh now" button when they
                                        want to see if FX has moved
                                        without waiting for the daily
                                        cron. Rate-limited.

The admin-tunable settings (markup %, overrides, supported_currencies)
flow through the existing ``/admin/settings`` PATCH path — no
dedicated endpoints needed for those.
"""
from __future__ import annotations
import time
from dataclasses import asdict
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.deps import get_db, get_admin_user
from app.core.exceptions import AppError
from app.core.limiter import limiter
from app.models.user import User
from app.services.fx import (
    FXError, NetworkError, SanityCapError, FXDataError,
    get_status, refresh_rates, symbol_for,
)

router = APIRouter()


class _CurrencyStatusOut(BaseModel):
    code: str
    symbol: str
    razorpay_supported: bool
    frankfurter_supported: bool
    has_live_rate: bool
    has_override: bool
    raw_inr_per_unit: Optional[float] = None
    effective_inr_per_unit: Optional[float] = None
    source: str           # RateSource enum value
    in_picker: bool


class FXStatusOut(BaseModel):
    last_fetched_at: Optional[datetime] = None
    age_days: Optional[float] = None
    stale: bool = False
    markup_percent: float = 0.0
    currencies: list[_CurrencyStatusOut] = []


class FXRefreshOut(BaseModel):
    """Result of admin-triggered refresh-now."""
    updated: bool
    fetched_at: Optional[datetime] = None
    rates_count: int = 0
    rejected_codes: list[str] = []
    elapsed_seconds: float = 0.0
    message: str = ""


# ============================================================ status

@router.get("/fx-status", response_model=FXStatusOut)
def fx_status():
    """Snapshot for the admin /admin/pricing dashboard.

    Includes ALL currencies the system knows about (live rates +
    overrides + INR), with their source and effective rate. Frontend
    renders this as a table.
    """
    report = get_status()
    return FXStatusOut(
        last_fetched_at=report.last_fetched_at,
        age_days=report.age_days,
        stale=report.stale,
        markup_percent=report.markup_percent,
        currencies=[
            _CurrencyStatusOut(
                code=c.code, symbol=c.symbol,
                razorpay_supported=c.razorpay_supported,
                frankfurter_supported=c.frankfurter_supported,
                has_live_rate=c.has_live_rate,
                has_override=c.has_override,
                raw_inr_per_unit=c.raw_inr_per_unit,
                effective_inr_per_unit=c.effective_inr_per_unit,
                source=c.source.value,
                in_picker=c.in_picker,
            ) for c in report.currencies
        ],
    )


# ====================================================== refresh-now

@router.post("/fx-refresh-now", response_model=FXRefreshOut)
@limiter.limit("5/hour")
def fx_refresh_now(request: Request,
                   db: Session = Depends(get_db),
                   admin: User = Depends(get_admin_user)):
    """Trigger an on-demand FX rate refresh from Frankfurter.

    Rate-limited (5/hour/admin) — Frankfurter publishes only once a
    day, so manual refreshes more often than ~hourly accomplish
    nothing. The limit prevents accidental rapid-fire clicks.

    Errors map cleanly:
      * NetworkError  → 502 (Frankfurter unreachable)
      * FXDataError   → 502 (Frankfurter response malformed)
      * SanityCapError → 400 (refused — bad upstream payload suspected)
    """
    start = time.monotonic()
    try:
        result = refresh_rates()
    except NetworkError as exc:
        audit_log(db, admin.id, "fx.refresh_now",
                  {"ok": False, "kind": "network"})
        raise AppError(str(exc), status_code=502, code="fx_network")
    except FXDataError as exc:
        audit_log(db, admin.id, "fx.refresh_now",
                  {"ok": False, "kind": "data"})
        raise AppError(str(exc), status_code=502, code="fx_data")
    except SanityCapError as exc:
        audit_log(db, admin.id, "fx.refresh_now",
                  {"ok": False, "kind": "sanity"})
        raise AppError(str(exc), status_code=400, code="fx_sanity")
    except FXError as exc:
        audit_log(db, admin.id, "fx.refresh_now",
                  {"ok": False, "kind": "fx"})
        raise AppError(str(exc), status_code=502, code="fx_error")

    audit_log(db, admin.id, "fx.refresh_now",
              {"ok": True,
               "rates_count": result.rates_count,
               "rejected": result.rejected_codes,
               "elapsed": round(time.monotonic() - start, 3)})
    return FXRefreshOut(
        updated=result.updated,
        fetched_at=result.fetched_at,
        rates_count=result.rates_count,
        rejected_codes=result.rejected_codes,
        elapsed_seconds=round(result.elapsed_seconds, 3),
        message=result.message,
    )
