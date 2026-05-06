"""Lead model (v4) — pre-signup capture for marketing & personalization."""
import enum
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, JSON, ForeignKey,
    Enum as SQLEnum, DateTime, Date, Index
)
from sqlalchemy.sql import func
from app.core.database import Base


class LeadSource(str, enum.Enum):
    LANDING_HERO   = "landing_hero"
    NEWSLETTER     = "newsletter"
    EXIT_INTENT    = "exit_intent"
    GATED_DOWNLOAD = "gated_download"
    BLOG           = "blog"
    PRICING_PAGE   = "pricing_page"
    EXAM_PREVIEW   = "exam_preview"
    DEMO_REQUEST   = "demo_request"


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_leads_email_created", "email", "created_at"),
    )

    id    = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False, index=True)
    name  = Column(String(120))
    phone = Column(String(32))
    # WhatsApp number (with country code stored separately for normalization)
    country_code    = Column(String(8))    # e.g. "+91"
    whatsapp_number = Column(String(32))   # local part, e.g. "9876543210"
    company = Column(String(120))
    role    = Column(String(120))

    source       = Column(SQLEnum(LeadSource), nullable=False)
    landing_url  = Column(String(500))
    referrer     = Column(String(500))
    utm_source   = Column(String(120))
    utm_medium   = Column(String(120))
    utm_campaign = Column(String(120))
    utm_term     = Column(String(120))
    utm_content  = Column(String(120))

    interests        = Column(JSON, default=list)
    target_exam_date = Column(Date)
    experience_level = Column(String(50))

    anon_id           = Column(String(36), index=True)
    converted_user_id = Column(Integer, ForeignKey("users.id"))

    consent_marketing = Column(Boolean, nullable=False, default=False)
    consent_at        = Column(DateTime(timezone=True))
    notes             = Column(Text)  # admin-only

    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())
