"""Public pricing endpoints — list active plans + quote with offer code.

These are read-only and don't require authentication. The order-create
endpoint in payments.py is what actually charges money; this layer is
purely for displaying prices.
"""
from pydantic import BaseModel
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from app.core.deps import get_db
from app.services.geoip import extract_client_ip, lookup as geo_lookup
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
    has_fx_rate: bool   # True if the code has either a live rate or
                        # an admin override. Always True for INR.
                        # False codes are filtered OUT in the response
                        # (frontend doesn't see them) — kept as a field
                        # for forward-compat with a "show all with
                        # disabled state" UI mode.


class CurrenciesOut(BaseModel):
    """Response of GET /pricing/currencies — what the picker offers.

    Surfaces only chargeable currencies (INR + those with live rates
    or admin overrides). The frontend populates the dropdown from this
    list directly.

    ``suggested_currency`` is the default the picker should pre-select,
    derived from the visitor's GeoIP country: India → INR (canonical,
    GST applies), everyone else → USD. Always one of the codes in
    ``options`` (falls back to USD/INR when geo is unavailable).
    """
    options: list[CurrencyOption]
    suggested_currency: str = "USD"


@router.get("/currencies", response_model=CurrenciesOut)
def list_currencies(request: Request):
    """Return the currencies the /pricing picker should show.

    The set is derived from the FX service's status:
      * INR is always present.
      * Currencies with a live (or stale-but-cached) Frankfurter rate.
      * Currencies with an admin override.

    Plus an optional admin filter (``pricing.supported_currencies``)
    that narrows the picker — handy when you want to show only a
    subset of the available rates (e.g. "only INR + USD for the
    Asia campaign").

    Read-only, public, no auth — same surface as /pricing/plans.
    """
    from app.services.fx import get_status, symbol_for
    status = get_status()
    options = []
    for cur in status.currencies:
        # Skip currencies that can't actually be charged AND aren't INR.
        # In practice: status.currencies only contains codes with at
        # least one source (live, override, or INR), but defensive.
        chargeable = (cur.code == "INR"
                       or cur.has_live_rate
                       or cur.has_override)
        if not chargeable:
            continue
        if not cur.in_picker:
            continue
        options.append(CurrencyOption(
            code=cur.code,
            symbol=symbol_for(cur.code),
            has_fx_rate=chargeable,
        ))
    # INR is the canonical first option — ensure it's at the top even
    # if the status enumeration ordered it differently.
    options.sort(key=lambda o: (o.code != "INR", o.code))

    # Default the picker by GeoIP: India → INR (canonical, GST applies);
    # everyone else → USD. Fail-open (private IP / no mmdb / miss all
    # resolve to None → USD). Never suggest a code the picker won't show.
    available = {o.code for o in options}
    client_ip = extract_client_ip(request)
    geo = geo_lookup(client_ip) if client_ip else None
    country = (geo.country if geo else "") or ""
    if country.upper() == "IN" and "INR" in available:
        suggested = "INR"
    elif "USD" in available:
        suggested = "USD"
    else:
        suggested = options[0].code if options else "INR"
    return CurrenciesOut(options=options, suggested_currency=suggested)
