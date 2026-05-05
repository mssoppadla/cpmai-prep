from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class CreateOrderIn(BaseModel):
    plan: Literal["pro", "enterprise"]
    amount_paise: int = Field(ge=100)


class CreateOrderOut(BaseModel):
    order_id: str
    amount: int
    currency: str
    razorpay_key_id: str


class VerifyPaymentIn(BaseModel):
    order_id: str
    payment_id: str
    signature: str
    plan: Literal["pro", "enterprise"]


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
    razorpay_order_id: str
    razorpay_payment_id: str | None
    amount_paise: int
    currency: str
    status: str
    raw_payload: dict | None
    created_at: datetime

    class Config:
        from_attributes = True
