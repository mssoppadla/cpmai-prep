"""Pydantic schemas for testimonial management."""
from datetime import datetime

from pydantic import BaseModel, Field


class TestimonialOut(BaseModel):
    """Public payload — what visitors see in the landing carousel."""
    id: int
    name: str
    role: str | None
    quote: str
    photo_url: str | None
    link_url: str | None
    display_order: int

    class Config:
        from_attributes = True


class TestimonialAdminOut(TestimonialOut):
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TestimonialIn(BaseModel):
    name:  str = Field(min_length=1, max_length=120)
    role:  str | None = Field(default=None, max_length=160)
    quote: str = Field(min_length=1, max_length=2000)
    # Relative /uploads/... URL (from /admin/uploads) or absolute https URL.
    photo_url: str | None = Field(default=None, max_length=1000)
    link_url:  str | None = Field(default=None, max_length=1000)
    display_order: int = 100
    is_active: bool = True
