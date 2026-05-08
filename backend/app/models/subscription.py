"""User subscriptions.

A `Subscription` is the resolved access state for a user after a
successful payment for a `Plan`. We keep `plan` (string) for legacy
free-tier rows and as a denormalised display label; `plan_id` (FK) is
the new authoritative pointer that drives paywall checks.

`expires_at` is the new time-bound field. Server sets it to
`paid_at + plan.duration_days` at verify time. The paywall treats a row
as active iff `status='active' AND (expires_at IS NULL OR expires_at > now)`.
NULL `expires_at` means "no expiry" — used for legacy free-tier rows
only; new paid rows always have an expiry.
"""
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    plan = Column(String(32), nullable=False)            # legacy label: free | pro | …
    plan_id = Column(Integer, ForeignKey("plans.id"), index=True)
    status = Column(String(32), nullable=False)          # active | cancelled | expired
    current_period_start = Column(DateTime(timezone=True))
    current_period_end   = Column(DateTime(timezone=True))
    expires_at           = Column(DateTime(timezone=True), index=True)
    razorpay_subscription_id = Column(String(64))
    cancelled_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())
