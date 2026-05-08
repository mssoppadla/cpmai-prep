"""Offer code schemas — admin CRUD + redemption."""
from typing import Literal, Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


DiscountType = Literal["percent", "flat"]


class OfferCodeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=48)
    description: Optional[str] = Field(default=None, max_length=240)
    discount_type: DiscountType = "percent"
    discount_value: int = Field(ge=0)
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    max_redemptions: Optional[int] = Field(default=None, ge=1)
    applies_to_plan_ids: Optional[list[int]] = None
    is_active: bool = True

    @field_validator("code")
    @classmethod
    def _normalise_code(cls, v):
        return (v or "").strip().upper()

    @field_validator("discount_value")
    @classmethod
    def _validate_value(cls, v, info):
        kind = info.data.get("discount_type")
        if kind == "percent" and not (0 <= v <= 100):
            raise ValueError("percent discount must be 0..100")
        return v


class OfferCodeUpdate(BaseModel):
    description: Optional[str] = None
    discount_type: Optional[DiscountType] = None
    discount_value: Optional[int] = Field(default=None, ge=0)
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    max_redemptions: Optional[int] = Field(default=None, ge=1)
    applies_to_plan_ids: Optional[list[int]] = None
    is_active: Optional[bool] = None


class OfferCodeAdminOut(BaseModel):
    id: int
    code: str
    description: Optional[str]
    discount_type: str
    discount_value: int
    valid_from: Optional[datetime]
    valid_until: Optional[datetime]
    max_redemptions: Optional[int]
    used_count: int
    applies_to_plan_ids: Optional[list[int]]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
