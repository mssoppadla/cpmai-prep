from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class CreateOrderIn(BaseModel):
    plan_slug: str = Field(min_length=1, max_length=140)
    offer_code: Optional[str] = Field(default=None, max_length=48)
    referrer: Optional[str] = Field(default=None, max_length=240)
    # Optional LinkedIn id/URL captured at checkout (same intent as the landing form) so we can
    # reach out to aspirants who paid. Stored as a lead (admins already surface lead LinkedIn).
    linkedin_id: Optional[str] = Field(default=None, max_length=255)
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
    # Which gateway minted this order. Frontend reads this to decide
    # whether to render the Razorpay popup or the PayPal Smart Button:
    #   "razorpay" → use razorpay_key_id below + Razorpay Checkout SDK
    #   "paypal"   → use paypal_client_id below + PayPal JS SDK
    provider: str = "razorpay"
    # Razorpay-specific (set when provider="razorpay", null otherwise).
    # Public key — safe to ship to the browser; that's what Razorpay
    # checkout SDK expects.
    razorpay_key_id: Optional[str] = None
    # PayPal-specific (set when provider="paypal", null otherwise).
    # paypal_client_id is the Client ID for the JS SDK; paypal_approval_url
    # is the fallback redirect URL if the frontend can't load the Smart
    # Button (very old browsers / blocked third-party scripts).
    paypal_client_id: Optional[str] = None
    paypal_approval_url: Optional[str] = None
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


# PayPal-specific 2-step capture. The PayPal Smart Button's onApprove
# callback hits this endpoint with the order_id; we then call PayPal's
# capture API to actually move the money. Razorpay doesn't have an
# analogue (their flow auto-captures on payment.captured webhook).
class PayPalCaptureIn(BaseModel):
    order_id: str                # PayPal order id returned by Smart Button


class PayPalCancelledIn(BaseModel):
    """Buyer bounced back from PayPal's hosted page without approving —
    PayPal appends ?token=<order_id> to our cancel_url; the frontend
    reports it here so the abandoned order is RECORDED instead of
    sitting in status='created' forever, indistinguishable from a
    closed tab."""
    order_id: str


class PayPalCancelledOut(BaseModel):
    status: str                  # the payment row's (possibly updated) status


class PayPalCaptureOut(BaseModel):
    status: str                  # "active" | "pending"
    plan_slug: str
    expires_at: Optional[datetime] = None   # null while still pending


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
    # Gateway-agnostic identifiers. provider_name distinguishes a
    # Razorpay-rail payment ("razorpay") from a PayPal-rail one
    # ("paypal") — the order_id / payment_id shapes differ between
    # providers but the admin view treats them uniformly.
    provider_name: str = "razorpay"
    provider_order_id: str
    provider_payment_id: Optional[str]
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
