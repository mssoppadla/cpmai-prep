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

    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())
