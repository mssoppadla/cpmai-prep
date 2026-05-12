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
    # Signed-in user clicked "Talk to a human" in the chat widget. They've
    # opted to leave a phone number for a follow-up call instead of (or in
    # addition to) the AI conversation.
    CHAT_CALLBACK  = "chat_callback"


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

    # ``values_callable`` makes SQLAlchemy use the Python enum's VALUES
    # (lowercase ``landing_hero``) instead of its NAMES (uppercase
    # ``LANDING_HERO``) for DDL generation and on-write serialization.
    #
    # Why: without this, SQLAlchemy stored the NAME but the Pydantic API
    # contract surfaces the VALUE — a quiet drift trap. We hit it in
    # May 2026 when migration 0012 added the lowercase value
    # ``chat_callback`` but inserts were silently sending ``CHAT_CALLBACK``
    # — every chat-callback POST 500'd until we hot-patched the enum.
    #
    # See ``QuestionType`` in ``app/models/question.py`` for the
    # documented pattern. Migrations 0016 + 0017 added every lowercase
    # value to the enum and translated existing rows to match.
    source       = Column(
        SQLEnum(LeadSource, name="leadsource",
                values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
    )
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
    # Rule-based score in [0, 100] computed at insert time by
    # ``app.services.lead_scoring.calculate_lead_score``. Nullable
    # because rows pre-dating this feature don't have one and we
    # intentionally don't backfill (see migration 0018 rationale).
    # Re-saving via the notes-patch endpoint also recomputes, so admin
    # can opt-in to score old leads one at a time.
    score            = Column(Integer)

    anon_id           = Column(String(36), index=True)
    converted_user_id = Column(Integer, ForeignKey("users.id"))

    consent_marketing = Column(Boolean, nullable=False, default=False)
    consent_at        = Column(DateTime(timezone=True))
    notes             = Column(Text)  # admin-only

    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())
