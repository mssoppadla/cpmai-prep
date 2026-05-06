"""Editable FAQ items shown on the public landing page."""
from sqlalchemy import Boolean, Column, DateTime, Integer, Text
from sqlalchemy.sql import func

from app.core.database import Base


class FaqItem(Base):
    __tablename__ = "faq_items"

    id            = Column(Integer, primary_key=True)
    question      = Column(Text, nullable=False)
    answer        = Column(Text, nullable=False)
    display_order = Column(Integer, nullable=False, default=100, index=True)
    is_active     = Column(Boolean, nullable=False, default=True, index=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True),
                           server_default=func.now(), onupdate=func.now())
