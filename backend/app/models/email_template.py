"""Email templates for the lead → auto-offer reply automation.

Each template is keyed by the lead ``source`` it serves (the "intent"):
a landing_hero sign-up can get different copy than an exit_intent one.
A single row with ``source = NULL`` is the **default** template used when
no source-specific template is active — so the automation always has
something to send.

The body is raw HTML authored in the admin UI (inline styles for
highlighted text / font sizes — the email-client-safe way). Placeholders
like ``{{name}}`` / ``{{offer_code}}`` are substituted at send time by
``app.services.email.mailer.render_template``.
"""
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, Index,
)
from sqlalchemy.sql import func
from app.core.database import Base


class EmailTemplate(Base):
    __tablename__ = "email_templates"
    __table_args__ = (
        # One ACTIVE template per source is enforced in the service layer
        # (a partial unique index can't easily express "active only"
        # across NULL source), but this plain index keeps the
        # select-by-source lookup fast.
        Index("ix_email_templates_source", "source"),
    )

    id        = Column(Integer, primary_key=True)
    # The lead source/intent this template serves (e.g. "landing_hero").
    # NULL = the default/fallback template. Free string rather than an
    # enum FK so adding a new LeadSource never requires a template
    # migration — an unmatched source simply falls back to the default.
    source    = Column(String(64), nullable=True)
    subject   = Column(String(240), nullable=False)
    html_body = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())
