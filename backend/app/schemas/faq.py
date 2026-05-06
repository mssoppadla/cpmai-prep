"""Pydantic schemas for FAQ management."""
from datetime import datetime

from pydantic import BaseModel, Field


class FaqOut(BaseModel):
    """Public payload — what learners see on the landing page."""
    id: int
    question: str
    answer: str
    display_order: int
    class Config:
        from_attributes = True


class FaqAdminOut(FaqOut):
    is_active: bool
    created_at: datetime
    updated_at: datetime


class FaqIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    answer:   str = Field(min_length=1, max_length=4000)
    display_order: int = 100
    is_active: bool = True
