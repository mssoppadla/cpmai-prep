from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, JSON
from sqlalchemy.sql import func
from app.core.database import Base


class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"))
    razorpay_order_id   = Column(String(64), unique=True, nullable=False)
    razorpay_payment_id = Column(String(64))
    amount_paise = Column(Integer, nullable=False)
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
