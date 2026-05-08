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

    final_price_paise: int
    stack_offer_with_discount: bool


class QuoteRequestIn(BaseModel):
    plan_slug: str
    offer_code: Optional[str] = None
