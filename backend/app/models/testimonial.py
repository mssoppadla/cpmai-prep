"""Aspirant testimonials shown in the landing-page carousel.

Admin-managed via /admin/testimonials (photo upload reuses the shared
/admin/uploads endpoint — ``photo_url`` stores the relative
``/uploads/...`` URL it returns). ``link_url`` is an optional external
proof link (LinkedIn recommendation, Trustpilot review, …) the public
card links out to.
"""
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.core.database import Base


class Testimonial(Base):
    __tablename__ = "testimonials"

    id            = Column(Integer, primary_key=True)
    name          = Column(String(120), nullable=False)
    # Short descriptor under the name ("AI Project Manager", "Product
    # Owner"). Optional — some aspirants prefer name-only attribution.
    role          = Column(String(160), nullable=True)
    quote         = Column(Text, nullable=False)
    # Relative /uploads/... URL from the shared admin upload endpoint,
    # or an absolute https:// URL. Empty/NULL renders an initials avatar.
    photo_url     = Column(Text, nullable=True)
    # External proof link (LinkedIn, Trustpilot, ...). NULL = card is
    # not clickable.
    link_url      = Column(Text, nullable=True)
    display_order = Column(Integer, nullable=False, default=100, index=True)
    is_active     = Column(Boolean, nullable=False, default=True, index=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True),
                           server_default=func.now(), onupdate=func.now())
