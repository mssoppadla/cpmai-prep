"""Public pricing endpoints — list active plans + quote with offer code.

These are read-only and don't require authentication. The order-create
endpoint in payments.py is what actually charges money; this layer is
purely for displaying prices.
"""
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
    """
    q = PricingService(db).quote(payload.plan_slug, payload.offer_code)
    return PriceQuoteOut(**q.to_dict())
