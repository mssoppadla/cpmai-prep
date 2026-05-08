"""Offer codes (discount coupons) + redemption ledger.

Codes are global with N redemptions: `max_redemptions` caps total uses
across all users (NULL = unlimited). `OfferRedemption` is an append-only
ledger so we can audit who used what and reverse a code that was abused.

Whether an offer code stacks on top of `discount_price_paise` is a global
admin toggle (`pricing.stack_offer_with_discount`), not per-code, by
design — keeps semantics predictable for users.
"""
from sqlalchemy import (
    Column, Integer, String, Boolean, ForeignKey, DateTime, Index,
    UniqueConstraint, JSON,
)
from sqlalchemy.sql import func
from app.core.database import Base


class OfferCode(Base):
    __tablename__ = "offer_codes"

    id              = Column(Integer, primary_key=True)
    code            = Column(String(48), unique=True, nullable=False, index=True)
    description     = Column(String(240))

    # "percent" → discount_value is 0..100 (whole percent).
    # "flat"    → discount_value is paise off the price.
    discount_type   = Column(String(16), nullable=False)
    discount_value  = Column(Integer, nullable=False)

    valid_from      = Column(DateTime(timezone=True))   # NULL = always
    valid_until     = Column(DateTime(timezone=True))   # NULL = forever

    max_redemptions = Column(Integer)                   # NULL = unlimited
    used_count      = Column(Integer, default=0, nullable=False)

    # Optional whitelist — empty/null means "applies to every plan".
    applies_to_plan_ids = Column(JSON)                  # list[int] | null

    is_active       = Column(Boolean, default=True, nullable=False, index=True)

    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())


class OfferRedemption(Base):
    __tablename__ = "offer_redemptions"
    __table_args__ = (
        Index("ix_offer_redemptions_user", "user_id"),
        Index("ix_offer_redemptions_code", "offer_code_id"),
        UniqueConstraint("offer_code_id", "payment_id",
                          name="uq_redemption_per_payment"),
    )

    id              = Column(Integer, primary_key=True)
    offer_code_id   = Column(Integer, ForeignKey("offer_codes.id", ondelete="RESTRICT"),
                              nullable=False)
    user_id         = Column(Integer, ForeignKey("users.id"), nullable=False)
    plan_id         = Column(Integer, ForeignKey("plans.id"), nullable=False)
    payment_id      = Column(Integer, ForeignKey("payments.id"), nullable=False)

    # Snapshots of what was applied — survives later edits to the offer
    # (e.g. admin changes discount_value).
    discount_paise  = Column(Integer, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
