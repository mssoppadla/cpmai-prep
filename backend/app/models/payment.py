from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, JSON
from sqlalchemy.sql import func
from app.core.database import Base


class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"))
    plan_id = Column(Integer, ForeignKey("plans.id"), index=True)
    # Provider-agnostic columns (migration 0020 renamed razorpay_* → provider_*).
    # `provider_name` tells callers which gateway minted the IDs:
    #   "razorpay" → INR rail; provider_order_id is Razorpay order id,
    #                provider_payment_id is razorpay_payment_id.
    #   "paypal"   → non-INR rail; provider_order_id is PayPal order id,
    #                provider_payment_id is PayPal capture id.
    # The discriminator drives which provider's verify/webhook handlers
    # apply when reconciling a Payment row.
    provider_name        = Column(String(32), nullable=False, default="razorpay",
                                   index=True)
    provider_order_id    = Column(String(64), unique=True, nullable=False)
    provider_payment_id  = Column(String(64))
    amount_paise = Column(Integer, nullable=False)         # final charged amount (post-discount)
    base_amount_paise   = Column(Integer)                  # pre-discount, for audit
    discount_paise      = Column(Integer, default=0)
    offer_code          = Column(String(48))               # snapshot, not FK (codes can be deleted)
    referrer            = Column(String(240))              # free-text "who referred me"
    # Ad-campaign attribution captured at order time from the SPA
    # tracker's session UTMs — lets admins answer 'revenue per
    # campaign'. journey_events/leads already carry these; payments
    # gained them 2026-07-13 for the ads rollout.
    utm_source   = Column(String(64))
    utm_medium   = Column(String(64))
    utm_campaign = Column(String(128))
    currency     = Column(String(8), nullable=False, default="INR")
    status       = Column(String(32), nullable=False)   # created|captured|failed|refunded
    idempotency_key = Column(String(64), unique=True, nullable=False)
    raw_payload  = Column(JSON)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id = Column(Integer, primary_key=True)
    event_id = Column(String(80), unique=True, nullable=False)
    payload  = Column(JSON)
    received_at  = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True))
