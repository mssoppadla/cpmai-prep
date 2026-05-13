from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class CreateOrderIn(BaseModel):
    plan_slug: str = Field(min_length=1, max_length=140)
    offer_code: Optional[str] = Field(default=None, max_length=48)
    referrer: Optional[str] = Field(default=None, max_length=240)
    # ISO-4217 currency code the user selected on /pricing. Defaults to
    # INR so existing integrations / production INR flow keep working
    # unchanged. Backend validates against ``pricing.supported_currencies``
    # and rejects with 400 if unsupported (we don't silently fall back
    # here — different from /pricing/quote, because a payment is about
    # to happen and we don't want to charge in INR if the user thought
    # they were paying in USD).
    currency: Optional[str] = Field(default="INR", min_length=3, max_length=3)


class CreateOrderOut(BaseModel):
    order_id: str
    amount: int                  # final amount in minor units of `currency`
    currency: str                # what gets charged (INR/USD/etc.)
    razorpay_key_id: str
    plan_slug: str
    plan_name: str
    base_amount: int             # INR paise (canonical breakdown stays in INR)
    discount_amount: int         # INR paise
    subtotal_amount: int         # post-discount, pre-GST, INR paise
    gst_percent: int
    gst_amount: int              # INR paise; 0 for non-INR orders
    offer_code: Optional[str]
    offer_applied: bool
    offer_reason: Optional[str]
    # Reference INR final (= subtotal + gst). For non-INR orders the
    # actual charge is in ``amount``/``currency``; this stays as the
    # INR-side reference for receipts and admin audits.
    final_inr_paise: int = 0
    # FX rate used (INR per 1 unit of charge currency). 1.0 for INR.
    fx_rate: float = 1.0


class VerifyPaymentIn(BaseModel):
    order_id: str
    payment_id: str
    signature: str


class VerifyPaymentOut(BaseModel):
    status: str                  # "active"
    plan_slug: str
    expires_at: datetime


class PaymentOut(BaseModel):
    id: int
    amount: int
    currency: str
    status: str
    masked_payment_id: str
    created_at: datetime

    class Config:
        from_attributes = True


class PaymentAdminOut(BaseModel):
    id: int
    user_id: int
    plan_id: Optional[int]
    razorpay_order_id: str
    razorpay_payment_id: Optional[str]
    amount_paise: int
    base_amount_paise: Optional[int]
    discount_paise: int
    offer_code: Optional[str]
    referrer: Optional[str]
    currency: str
    status: str
    raw_payload: Optional[dict]
    created_at: datetime

    class Config:
        from_attributes = True
