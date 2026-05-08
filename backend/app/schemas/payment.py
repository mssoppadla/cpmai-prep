from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class CreateOrderIn(BaseModel):
    plan_slug: str = Field(min_length=1, max_length=140)
    offer_code: Optional[str] = Field(default=None, max_length=48)
    referrer: Optional[str] = Field(default=None, max_length=240)


class CreateOrderOut(BaseModel):
    order_id: str
    amount: int                  # final amount in paise (post-discount + GST)
    currency: str
    razorpay_key_id: str
    plan_slug: str
    plan_name: str
    base_amount: int
    discount_amount: int
    subtotal_amount: int         # post-discount, pre-GST
    gst_percent: int
    gst_amount: int
    offer_code: Optional[str]
    offer_applied: bool
    offer_reason: Optional[str]


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
