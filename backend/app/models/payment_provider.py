"""Payment provider config — secrets encrypted at rest with Fernet.

Mirrors the llm_providers pattern: multiple providers can coexist, exactly
one is active at a time (chosen via system_settings.payment.active_provider_id),
and switching is one API call away — no app restart.
"""
from sqlalchemy import (
    Column, Integer, String, Boolean, JSON, DateTime, LargeBinary, ForeignKey
)
from sqlalchemy.sql import func
from app.core.database import Base


class PaymentProviderConfig(Base):
    __tablename__ = "payment_providers"

    id            = Column(Integer, primary_key=True)
    name          = Column(String(80), unique=True, nullable=False)
    provider_type = Column(String(32), nullable=False)        # razorpay | stripe
    mode          = Column(String(16), nullable=False, default="test")  # test | live
    display_name  = Column(String(120))                       # shown to learners
    public_key    = Column(String(120))                       # razorpay key_id (not secret)

    # Encrypted at rest (Fernet via app.core.crypto)
    api_secret_encrypted     = Column(LargeBinary)            # razorpay key_secret
    webhook_secret_encrypted = Column(LargeBinary)            # webhook signing secret

    config        = Column(JSON, default=dict)                # provider-specific options
    is_enabled    = Column(Boolean, default=True, nullable=False, index=True)
    priority      = Column(Integer, default=100, nullable=False)

    # Listing control-plane (multi-gateway Phase 1, migration 0047).
    # is_enabled = "can SERVICE past payments" (webhooks, refunds);
    # listed_*   = "can SELL new payments" on that rail. Separating the
    # two is what makes a gateway suspension a 30-second delist instead
    # of an outage: unlist → customers see only active gateways, while
    # historical payments keep verifying. intl_rank orders listed intl
    # entries (lowest wins = preferred / auto-mode choice).
    listed_for_inr  = Column(Boolean, default=False, nullable=False)
    listed_for_intl = Column(Boolean, default=False, nullable=False)
    intl_rank       = Column(Integer, default=100, nullable=False)

    # Webhook health (migration 0049): stamped whenever a delivery
    # verifies against THIS config's secret. A listed account whose
    # webhooks are disabled at the gateway silently loses captures —
    # the card surfaces staleness so that's visible at a glance.
    last_webhook_at = Column(DateTime(timezone=True), nullable=True)

    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())
