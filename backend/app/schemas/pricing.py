"""Public pricing wire types (mirrors PriceQuote dataclass)."""
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

    # Display block — the currency the caller asked us to compute for.
    # Defaults to INR (mirror of the block above). When non-INR, the
    # display amount is the FX-converted subtotal (GST excluded —
    # international customers don't pay Indian GST). UI shows BOTH the
    # INR block AND the display amount so the user sees the comparison;
    # checkout charges in display_currency.
    display_currency: str = "INR"
    display_amount_minor: int = 0
    display_fx_rate: Optional[float] = 1.0
    display_currency_supported: bool = True


class QuoteRequestIn(BaseModel):
    plan_slug: str
    offer_code: Optional[str] = None
    # ISO-4217 code. Defaults to INR so existing callers (incl. the
    # production payment flow) keep working unchanged. Frontend passes
    # the user's selected currency. Backend validates against
    # ``pricing.supported_currencies`` and falls back to INR with
    # ``display_currency_supported=False`` for anything unsupported.
    currency: str = "INR"
