"""Public pricing endpoints — list active plans + quote with offer code.

These are read-only and don't require authentication. The order-create
endpoint in payments.py is what actually charges money; this layer is
purely for displaying prices.
"""
from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.deps import get_db
from app.models.plan import Plan
from app.schemas.plan import PlanPublicOut
from app.schemas.pricing import PriceQuoteOut, QuoteRequestIn
from app.services.pricing_service import PricingService

router = APIRouter()


@router.get("/plans", response_model=list[PlanPublicOut])
def list_active_plans(db: Session = Depends(get_db)):
    rows = (db.query(Plan).filter_by(is_active=True)
            .order_by(Plan.display_order, Plan.id).all())
    return [PlanPublicOut.from_row(r) for r in rows]


@router.post("/quote", response_model=PriceQuoteOut)
def quote(payload: QuoteRequestIn, db: Session = Depends(get_db)):
    """Return the final price for a plan, applying an optional offer code.

    Failures are SOFT — invalid/expired/wrong-plan codes return a quote
    where `offer_applied=false` and `offer_reason` explains why. The
    exception is an unknown plan, which raises 404.

    The ``currency`` field in the request body drives the ``display_*``
    block in the response. Unsupported currencies (not in the admin's
    ``pricing.supported_currencies`` setting) fall back to INR with
    ``display_currency_supported=false`` — frontend should refuse
    checkout in that case.
    """
    q = PricingService(db).quote(
        payload.plan_slug, payload.offer_code,
        currency=payload.currency or "INR",
    )
    return PriceQuoteOut(**q.to_dict())


class CurrencyOption(BaseModel):
    code: str        # ISO-4217 (e.g. "USD")
    symbol: str      # display symbol (e.g. "$")
    has_fx_rate: bool   # False if admin added the code but no FX rate
                        # configured yet — frontend shows it disabled


class CurrenciesOut(BaseModel):
    """Response of GET /pricing/currencies — what the picker offers.

    Frontend uses this to populate the dropdown AND to know which codes
    are actually charge-ready vs. picker-but-no-FX (admin half-configured).
    """
    options: list[CurrencyOption]


# Symbol map. We hand-roll a few common ones rather than pulling in
# `babel` — 8 currencies' worth of symbols is fine to keep inline.
# Anything not in the map falls back to the ISO code itself.
_CURRENCY_SYMBOLS: dict[str, str] = {
    "INR": "₹",   # ₹
    "USD": "$",
    "EUR": "€",   # €
    "GBP": "£",   # £
    "JPY": "¥",   # ¥
    "SGD": "S$",
    "AED": "AED",
    "CAD": "CA$",
    "AUD": "A$",
    "NZD": "NZ$",
    "ZAR": "R",
    "CNY": "¥",
}


@router.get("/currencies", response_model=CurrenciesOut)
def list_currencies():
    """Return the currencies the /pricing picker should show, in the
    admin-configured order. Includes a flag for "has FX rate" so the
    frontend can render unconfigured codes disabled with a tooltip.

    Read-only, public, no auth — same surface as /pricing/plans.
    """
    codes = PricingService._supported_currencies()
    rates = PricingService._fx_rates()
    options = []
    for code in codes:
        options.append(CurrencyOption(
            code=code,
            symbol=_CURRENCY_SYMBOLS.get(code, code),
            has_fx_rate=(code in rates),
        ))
    return CurrenciesOut(options=options)
