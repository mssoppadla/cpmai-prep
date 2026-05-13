"""Public pricing wire types (mirrors PriceQuote dataclass)."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class PriceQuoteOut(BaseModel):
    plan_id: int
    plan_slug: str
    plan_name: str
    currency: str
    base_price_paise: int
    discount_price_paise: Optional[int]
    effective_before_offer_paise: int

    offer_code: Optional[str]
    offer_applied: bool
    offer_reason: Optional[str]
    offer_discount_paise: int

    # Pre-GST subtotal (post-offer). UI uses this as the "Subtotal" line.
    subtotal_paise: int

    # GST line. gst_percent==0 means "no GST line shown".
    gst_percent: int
    gst_paise: int

    # final_price_paise = subtotal_paise + gst_paise. This is what the
    # user pays when currency == "INR" (the canonical INR breakdown).
    final_price_paise: int
    stack_offer_with_discount: bool

    # Display block — currency the caller asked us to compute for.
    # For INR: mirrors the INR block above.
    # For non-INR + live FX: subtotal-at-mid-market + transparent
    #   markup line = total. UI shows the markup as a separate fee
    #   line so the buyer can see it on the receipt rather than
    #   having it buried in the FX rate.
    # For non-INR + admin override: rate as-is, no markup line.
    # For unsupported currency: mirrors INR, display_currency_supported=false.
    display_currency: str = "INR"
    display_amount_minor: int = 0
    display_fx_rate: Optional[float] = 1.0
    display_fx_rate_raw: Optional[float] = None
    display_currency_supported: bool = True
    display_fx_source: str = "inr"
    display_fx_fetched_at: Optional[datetime] = None
    display_subtotal_minor: int = 0
    display_markup_percent: float = 0.0
    display_markup_minor: int = 0


class QuoteRequestIn(BaseModel):
    plan_slug: str
    offer_code: Optional[str] = None
    # ISO-4217 code. Defaults to INR so existing callers (incl. the
    # production payment flow) keep working unchanged. Frontend passes
    # the user's selected currency. Backend validates against
    # ``pricing.supported_currencies`` and falls back to INR with
    # ``display_currency_supported=False`` for anything unsupported.
    currency: str = "INR"
